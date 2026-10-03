"""FastAPI backend for higgsfield-genjutsu-unlimited v4.0.

Endpoints:
  GET  /                    static Next.js frontend (served by this same service)
  POST /generate            (multipart: video, images[], prompt, mode) -> { jobId }
  GET  /jobs/{id}/stream    SSE: log / progress / done events
  GET  /jobs/{id}/video     FileResponse of the result mp4
  GET  /config              { authRequired } — tells the UI whether to ask for a key
  GET  /health              liveness probe
  GET  /proxies             proxy pool status
  POST /proxies             replace the proxy pool at runtime
  GET  /stats               account + proxy statistics

Deployment note: this app is designed to run as ONE service. It serves the
statically-exported Next.js frontend itself, so there is no CORS, no second
host, and no NEXT_PUBLIC_BACKEND_URL to keep in sync.
"""
import os
import uuid
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List
from collections import defaultdict, deque

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from creator import HiggsfieldCreator
from database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("main")

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# The built frontend lives here (see Dockerfile). If it is missing we simply
# skip the mount so the API still runs standalone during development.
STATIC_DIR = Path(os.getenv("STATIC_DIR", "./static"))

CORS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# --- Security config ---
API_KEY = os.getenv("API_KEY", "")  # empty = auth disabled (default for self-hosting)
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

# Playwright picks the multipart Content-Type from the file extension. An
# extensionless temp file is uploaded as application/octet-stream and
# Higgsfield rejects it, so the extension is preserved all the way through.
VIDEO_SUFFIXES = {".mp4": ".mp4", ".mov": ".mov", ".webm": ".webm", ".avi": ".avi", ".ogv": ".ogv",
                  ".ogg": ".ogv", ".m4v": ".mp4", ".qt": ".mov"}
IMAGE_SUFFIXES = {".png": ".png", ".jpg": ".jpg", ".jpeg": ".jpg", ".webp": ".webp",
                  ".gif": ".gif", ".bmp": ".bmp"}

# Paths that require the API key when one is configured. Static assets are
# deliberately absent so the UI can always load and ask the user for the key.
PROTECTED_PREFIXES = ("/generate", "/jobs", "/proxies", "/stats")

# Default to ONE worker. Each worker is a full headless Chromium (roughly
# 250-400 MB); more than one will OOM a 512 MB instance.
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "1"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    for i in range(MAX_WORKERS):
        asyncio.create_task(worker(f"w{i}"))
    asyncio.create_task(jobs_cleanup_loop())
    log.info(f"started with {MAX_WORKERS} worker(s)")
    yield


app = FastAPI(title="higgsfield-genjutsu-unlimited", version="4.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Gap 1: API Key auth middleware =====

class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Reject protected API calls without a valid X-API-Key when API_KEY is set.

    The UI itself is always served — a browser cannot attach a header to the
    initial HTML request. Only the job/proxy endpoints are gated.
    """

    async def dispatch(self, request: Request, call_next):
        if not API_KEY:
            return await call_next(request)
        path = request.url.path
        if not path.startswith(PROTECTED_PREFIXES):
            return await call_next(request)
        # EventSource cannot set headers, so ?api_key= is accepted for streams.
        provided = request.headers.get("X-API-Key", "") or request.query_params.get("api_key", "")
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
    if RATE_LIMIT > 0 and request.url.path.startswith(PROTECTED_PREFIXES):
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
        self.video_source: Optional[Path] = None
        self.image_sources: list[Path] = []


JOBS: dict[str, Job] = {}
WORK_QUEUE: asyncio.Queue = asyncio.Queue()


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
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode == 0:
            return float(stdout.decode().strip())
    except Exception:
        log.warning("ffprobe unavailable — skipping duration validation")
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


def _safe_unlink(paths: list[Path]) -> None:
    for p in paths:
        try:
            if p and p.exists():
                p.unlink()
        except Exception:
            pass


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

        async def progress_loop(_job=job):
            p = 0
            while _job.status == "running" and p < 95:
                await asyncio.sleep(6)
                p = min(95, p + 5)
                _job.progress = p
                await push_event(_job, "progress", str(p))

        pt = asyncio.create_task(progress_loop())

        try:
            video = await creator.run(
                str(job.video_source), job.prompt, image_paths=job.image_sources
            )
            job.video_path = video
            job.progress = 100
            job.status = "done"
            await push_event(job, "progress", "100")
            await push_event(job, "done", {"fileName": video.name, "jobId": jid})
        except Exception as e:
            log.exception("job failed")
            job.status = "error"
            job.error = str(e)
            job.progress = 0
            await push_event(job, "progress", "0")
            await push_event(job, "log", {"level": "err", "msg": str(e)})
            await push_event(job, "error", {"error": str(e)})
        finally:
            pt.cancel()
            try:
                await pt
            except asyncio.CancelledError:
                pass
            # The creator has already copied the result into VIDEO_DIR, so every
            # temp input can go now.
            _safe_unlink([job.video_source, *job.image_sources])


@app.get("/health")
async def health():
    return {"status": "ok", "jobs": len(JOBS), "workers": MAX_WORKERS}


@app.get("/config")
async def config():
    """Lets the UI know whether it must prompt for an API key."""
    return {"authRequired": bool(API_KEY), "maxImages": MAX_IMAGES,
            "minDuration": MIN_DURATION, "maxDuration": MAX_DURATION}


# ===== Proxy management (runtime updates from UI) =====

@app.get("/proxies")
async def get_proxies():
    from creator import PROXY_POOL
    return PROXY_POOL.status()


@app.post("/proxies")
async def set_proxies(request: Request):
    body = await request.json()
    new_proxies = body.get("proxies", [])
    if not isinstance(new_proxies, list):
        raise HTTPException(400, "proxies must be a list of strings")
    from creator import PROXY_POOL
    from proxy_manager import parse_proxy_line
    # Parse IP:PORT:USERNAME:PASSWORD → socks5h://...
    parsed = [parse_proxy_line(p) for p in new_proxies if p and p.strip()]
    PROXY_POOL.update_proxies(parsed)
    log.info(f"proxy pool updated: {len(parsed)} proxies")
    return {"count": PROXY_POOL.size, "status": "updated"}


@app.get("/stats")
async def stats():
    """Account + proxy statistics."""
    from database import list_accounts
    from creator import PROXY_POOL
    accounts = await list_accounts()
    active = sum(1 for a in accounts if a.get("status") == "active")
    banned = sum(1 for a in accounts if a.get("status") == "banned")
    exhausted = sum(1 for a in accounts if a.get("credits", 0) == 0)
    return {
        "accounts": {"total": len(accounts), "active": active, "banned": banned, "exhausted": exhausted},
        "proxies": PROXY_POOL.status(),
        "workers": MAX_WORKERS,
    }


@app.post("/generate")
async def generate(
    video: UploadFile = File(...),
    images: List[UploadFile] = File(default=[]),
    prompt: str = Form(""),  # was Form(...) — FastAPI treats empty string as missing
    mode: str = Form("motion_transfer"),
):
    if not video.content_type or video.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(400, f"video must be one of {ALLOWED_VIDEO_TYPES}, got {video.content_type}")
    video_data = await video.read()
    if len(video_data) > MAX_VIDEO_SIZE:
        raise HTTPException(400, f"video too large (max {MAX_VIDEO_SIZE // (1024 * 1024)} MB)")
    if len(images) > MAX_IMAGES:
        raise HTTPException(400, f"too many images (max {MAX_IMAGES})")

    jid = uuid.uuid4().hex[:12]
    job = Job(jid)
    job.prompt = prompt
    job.mode = mode

    suffix = VIDEO_SUFFIXES.get(Path(video.filename or "").suffix.lower(), ".mp4")
    video_path = UPLOAD_DIR / f"{jid}_video{suffix}"
    video_path.write_bytes(video_data)

    duration = await _probe_duration(video_path)
    if duration is not None:
        if duration < MIN_DURATION or duration > MAX_DURATION:
            video_path.unlink(missing_ok=True)
            raise HTTPException(
                400,
                f"video duration must be {MIN_DURATION:.0f}-{MAX_DURATION:.0f}s "
                f"(got {duration:.1f}s)",
            )
        job.logs.append({"level": "info", "msg": f"video duration: {duration:.1f}s"})

    image_paths: list[Path] = []
    for i, img in enumerate(images[:MAX_IMAGES]):
        if not img.content_type or img.content_type not in ALLOWED_IMAGE_TYPES:
            continue
        img_data = await img.read()
        if len(img_data) > MAX_IMAGE_SIZE:
            continue
        img_suffix = IMAGE_SUFFIXES.get(Path(img.filename or "").suffix.lower(), ".jpg")
        ipath = UPLOAD_DIR / f"{jid}_img_{i}{img_suffix}"
        ipath.write_bytes(img_data)
        image_paths.append(ipath)

    job.video_source = video_path
    job.image_sources = image_paths
    job.logs.append({"level": "info", "msg": f"reference video + {len(image_paths)} image(s) saved"})

    JOBS[jid] = job
    await WORK_QUEUE.put(jid)
    return {"jobId": jid}


@app.get("/jobs/{jid}/stream")
async def stream(jid: str, request: Request):
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
async def video(jid: str):
    job = JOBS.get(jid)
    if not job or not job.video_path:
        raise HTTPException(404, "video not ready")
    return FileResponse(job.video_path, media_type="video/mp4", filename=f"{jid}.mp4")


# ===== Static frontend (mounted LAST so it never shadows the API) =====

def _wants_html(scope) -> bool:
    """True when the client sent an Accept header that includes text/html."""
    for key, value in scope.get("headers", []):
        if key == b"accept":
            return b"text/html" in value
    return False


class SPAStaticFiles(StaticFiles):
    """Serve the Next.js export and fall back to the app shell for client routes.

    `html=True` does NOT raise on a missing path — it renders 404.html with a
    404 status. So the fallback inspects the response rather than only catching
    an exception. Only requests that actually ask for HTML get the shell; a
    missing .js or .css still 404s, so a broken asset link stays visible
    instead of silently returning HTML in place of a script.
    """

    async def get_response(self, path: str, scope):
        response = None
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise

        if response is None or response.status_code == 404:
            if _wants_html(scope):
                try:
                    return await super().get_response("index.html", scope)
                except Exception:
                    pass
            if response is not None:
                return response
            raise StarletteHTTPException(status_code=404)
        return response


if STATIC_DIR.is_dir():
    app.mount("/", SPAStaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")
    log.info(f"serving frontend from {STATIC_DIR}")
else:
    log.warning(f"no frontend build at {STATIC_DIR} — running API only")
