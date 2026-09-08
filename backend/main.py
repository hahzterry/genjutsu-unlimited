"""FastAPI backend for higgsfield-genjutsu-unlimited v3.0.

Endpoints:
  POST /generate            (multipart: video, images[], prompt, mode) -> { jobId }
  GET  /jobs/{id}/stream    SSE: log / progress / done events
  GET  /jobs/{id}/video     FileResponse of the result mp4
  GET  /health              liveness probe

Security (all gaps fixed):
  - API_KEY auth via X-API-Key header (Gap 1)
  - Configurable rate limiting per IP (Gap 2)
  - JOBS TTL cleanup — no memory leak (Gap 3)
"""
import os
import uuid
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional, List
from collections import defaultdict, deque

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from creator import HiggsfieldCreator
from database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("main")

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CORS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]

# --- Security config ---
API_KEY = os.getenv("API_KEY", "")  # if empty, auth disabled (local dev)
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "0"))  # 0 = disabled, N = max req/min per IP
JOB_TTL = int(os.getenv("JOB_TTL", "3600"))  # seconds before old jobs are cleaned up

# --- File limits ---
MAX_IMAGES = 30
MAX_VIDEO_SIZE = 100 * 1024 * 1024
MAX_IMAGE_SIZE = 20 * 1024 * 1024
MIN_DURATION = 4.0
MAX_DURATION = 30.0
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/x-msvideo", "video/ogg"}
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}

app = FastAPI(title="higgsfield-genjutsu-unlimited", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Gap 1: API Key auth middleware =====

class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Reject requests without a valid X-API-Key header if API_KEY is set."""
    EXEMPT_PATHS = {"/health"}

    async def dispatch(self, request: Request, call_next):
        if not API_KEY:
            return await call_next(request)
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)
        provided = request.headers.get("X-API-Key", "")
        if provided != API_KEY:
            return JSONResponse({"error": "invalid or missing API key"}, status_code=401)
        return await call_next(request)

app.add_middleware(ApiKeyMiddleware)


# ===== Gap 2: Rate limiting (sliding window per IP) =====

class RateLimiter:
    """Simple in-memory sliding-window rate limiter. 0 = disabled."""
    def __init__(self, max_per_min: int):
        self.max = max_per_min
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, ip: str) -> bool:
        if self.max <= 0:
            return True
        now = time.time()
        window = self.hits[ip]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= self.max:
            return False
        window.append(now)
        return True

rate_limiter = RateLimiter(RATE_LIMIT)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if RATE_LIMIT > 0 and request.url.path not in {"/health"}:
        ip = request.client.host if request.client else "unknown"
        if not rate_limiter.check(ip):
            return JSONResponse({"error": "rate limit exceeded"}, status_code=429)
    return await call_next(request)


# ===== Job store + worker pool =====

class Job:
    def __init__(self, jid: str):
        self.id = jid
        self.status = "queued"
        self.progress = 0
        self.prompt = ""
        self.mode = "motion_transfer"
        self.logs: list[dict] = []
        self.video_path: Optional[Path] = None
        self.error: Optional[str] = None
        self.queue: asyncio.Queue = asyncio.Queue()
        self.created_at = time.time()


JOBS: dict[str, Job] = {}
WORK_QUEUE: asyncio.Queue = asyncio.Queue()
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))


async def push_event(job: Job, event: str, data) -> None:
    payload = data if isinstance(data, str) else json.dumps(data)
    await job.queue.put((event, payload))


async def _probe_duration(path: Path) -> Optional[float]:
    """Return video duration in seconds via ffprobe, or None if unavailable."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            return float(stdout.decode().strip())
    except Exception:
        pass
    return None


# ===== Gap 3: JOBS TTL cleanup =====

async def jobs_cleanup_loop():
    """Background task: remove completed jobs older than JOB_TTL seconds."""
    while True:
        await asyncio.sleep(300)  # check every 5 min
        now = time.time()
        expired = [jid for jid, j in JOBS.items()
                   if j.status in ("done", "error") and now - j.created_at > JOB_TTL]
        for jid in expired:
            job = JOBS.pop(jid, None)
            if job and job.video_path:
                try:
                    job.video_path.unlink(missing_ok=True)
                except Exception:
                    pass
        if expired:
            log.info(f"cleaned up {len(expired)} expired jobs")


async def worker(name: str) -> None:
    log.info(f"worker {name} ready")
    while True:
        jid = await WORK_QUEUE.get()
        job = JOBS.get(jid)
        if not job:
            continue
        job.status = "running"
        await push_event(job, "log", {"level": "info", "msg": f"worker {name} picked job"})

        async def log_cb(level: str, msg: str, _job=job):
            _job.logs.append({"level": level, "msg": msg})
            await push_event(_job, "log", {"level": level, "msg": msg})

        creator = HiggsfieldCreator(log_cb=log_cb)
        video_path = UPLOAD_DIR / f"{jid}_video"
        image_paths: list[Path] = getattr(job, "_image_paths", [])

        async def progress_loop(_job=job):
            p = 0
            while _job.status == "running" and p < 95:
                await asyncio.sleep(4)
                p = min(95, p + 5)
                _job.progress = p
                await push_event(_job, "progress", str(p))

        pt = asyncio.create_task(progress_loop())

        try:
            video = await creator.run(str(video_path), job.prompt, image_paths=image_paths)
            job.video_path = video
            job.progress = 100
            job.status = "done"
            await push_event(job, "progress", "100")
            await push_event(job, "done", {"fileName": video.name, "jobId": jid})
        except Exception as e:
            log.exception("job failed")
            job.status = "error"
            job.error = str(e)
            await push_event(job, "log", {"level": "err", "msg": str(e)})
            await push_event(job, "error", {"error": str(e)})
        finally:
            pt.cancel()
            try:
                await pt
            except asyncio.CancelledError:
                pass
            for p in [video_path] + image_paths:
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass


@app.on_event("startup")
async def startup() -> None:
    await init_db()
    for i in range(MAX_WORKERS):
        asyncio.create_task(worker(f"w{i}"))
    asyncio.create_task(jobs_cleanup_loop())


@app.get("/health")
async def health():
    return {"status": "ok", "jobs": len(JOBS), "workers": MAX_WORKERS}


# ===== Proxy management (runtime updates from UI) =====

@app.get("/proxies")
async def get_proxies():
    from creator import PROXY_POOL
    return {"count": PROXY_POOL.size, "proxies": [f"{p.split('@')[0]}@***" for p in PROXY_POOL.proxies]}


@app.post("/proxies")
async def set_proxies(request: Request):
    if API_KEY:
        qkey = request.query_params.get("api_key", "") or request.headers.get("X-API-Key", "")
        if qkey != API_KEY:
            raise HTTPException(401, "invalid or missing API key")
    body = await request.json()
    new_proxies = body.get("proxies", [])
    if not isinstance(new_proxies, list):
        raise HTTPException(400, "proxies must be a list of strings")
    # Update the runtime proxy pool
    from creator import PROXY_POOL
    PROXY_POOL.update_proxies(new_proxies)
    log.info(f"proxy pool updated: {len(new_proxies)} proxies")
    return {"count": len(new_proxies), "status": "updated"}


@app.post("/generate")
async def generate(
    video: UploadFile = File(...),
    images: List[UploadFile] = File(default=[]),
    prompt: str = Form(...),
    mode: str = Form("motion_transfer"),
):
    if not video.content_type or video.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(400, f"video must be one of {ALLOWED_VIDEO_TYPES}, got {video.content_type}")
    video_data = await video.read()
    if len(video_data) > MAX_VIDEO_SIZE:
        raise HTTPException(400, f"video too large (max {MAX_VIDEO_SIZE // (1024*1024)} MB)")
    if len(images) > MAX_IMAGES:
        raise HTTPException(400, f"too many images (max {MAX_IMAGES})")

    jid = uuid.uuid4().hex[:12]
    job = Job(jid)
    job.prompt = prompt
    job.mode = mode

    video_path = UPLOAD_DIR / f"{jid}_video"
    video_path.write_bytes(video_data)

    duration = await _probe_duration(video_path)
    if duration is not None:
        if duration < MIN_DURATION or duration > MAX_DURATION:
            video_path.unlink(missing_ok=True)
            raise HTTPException(400, f"video duration must be {MIN_DURATION}-{MAX_DURATION}s (got {duration:.1f}s)")
        job.logs.append({"level": "info", "msg": f"video duration: {duration:.1f}s"})

    image_paths: list[Path] = []
    for i, img in enumerate(images[:MAX_IMAGES]):
        if not img.content_type or img.content_type not in ALLOWED_IMAGE_TYPES:
            continue
        img_data = await img.read()
        if len(img_data) > MAX_IMAGE_SIZE:
            continue
        ipath = UPLOAD_DIR / f"{jid}_img_{i}"
        ipath.write_bytes(img_data)
        image_paths.append(ipath)

    job.logs.append({"level": "info", "msg": f"reference video + {len(image_paths)} image(s) saved"})
    job._image_paths = image_paths  # type: ignore

    JOBS[jid] = job
    await WORK_QUEUE.put(jid)
    return {"jobId": jid}


@app.get("/jobs/{jid}/stream")
async def stream(jid: str, request: Request):
    # EventSource can't set headers, so allow ?api_key= query param as fallback
    if API_KEY:
        qkey = request.query_params.get("api_key", "")
        if qkey != API_KEY:
            raise HTTPException(401, "invalid or missing API key")

    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "job not found")

    async def gen():
        for l in job.logs:
            yield f"event: log\ndata: {json.dumps(l)}\n\n"
        while job.status not in ("done", "error"):
            try:
                event, data = await asyncio.wait_for(job.queue.get(), timeout=15)
                yield f"event: {event}\ndata: {data}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
        while not job.queue.empty():
            event, data = job.queue.get_nowait()
            yield f"event: {event}\ndata: {data}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/jobs/{jid}/video")
async def video(jid: str, request: Request):
    if API_KEY:
        qkey = request.query_params.get("api_key", "")
        if qkey != API_KEY:
            raise HTTPException(401, "invalid or missing API key")
    job = JOBS.get(jid)
    if not job or not job.video_path:
        raise HTTPException(404, "video not ready")
    return FileResponse(job.video_path, media_type="video/mp4",
                        filename=job.video_path.name)
