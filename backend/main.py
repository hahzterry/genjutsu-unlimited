"""FastAPI backend for higgsfield-genjutsu-unlimited.

Endpoints:
  POST /generate            (multipart: file, prompt) -> { jobId }
  GET  /jobs/{id}/stream    SSE: log / progress / done events
  GET  /jobs/{id}/video     FileResponse of the result mp4
  GET  /health              liveness probe
"""
import os
import uuid
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

from creator import HiggsfieldCreator
from database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("main")

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CORS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]

app = FastAPI(title="higgsfield-genjutsu-unlimited", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Job:
    def __init__(self, jid: str):
        self.id = jid
        self.status = "queued"          # queued | running | done | error
        self.progress = 0
        self.prompt = ""
        self.logs: list[dict] = []
        self.video_path: Optional[Path] = None
        self.error: Optional[str] = None
        self.queue: asyncio.Queue = asyncio.Queue()


JOBS: dict[str, Job] = {}
WORK_QUEUE: asyncio.Queue = asyncio.Queue()
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))


async def push_event(job: Job, event: str, data) -> None:
    payload = data if isinstance(data, str) else json.dumps(data)
    await job.queue.put((event, payload))


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
        ref_path = UPLOAD_DIR / f"{jid}_ref"

        async def progress_loop(_job=job):
            p = 0
            while _job.status == "running" and p < 95:
                await asyncio.sleep(4)
                p = min(95, p + 5)
                _job.progress = p
                await push_event(_job, "progress", str(p))

        pt = asyncio.create_task(progress_loop())

        try:
            video = await creator.run(str(ref_path), job.prompt)
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


@app.on_event("startup")
async def startup() -> None:
    await init_db()
    for i in range(MAX_WORKERS):
        asyncio.create_task(worker(f"w{i}"))


@app.get("/health")
async def health():
    return {"status": "ok", "jobs": len(JOBS)}


@app.post("/generate")
async def generate(file: UploadFile = File(...), prompt: str = Form(...)):
    jid = uuid.uuid4().hex[:12]
    job = Job(jid)
    job.prompt = prompt
    ref_path = UPLOAD_DIR / f"{jid}_ref"
    with open(ref_path, "wb") as f:
        f.write(await file.read())
    JOBS[jid] = job
    await WORK_QUEUE.put(jid)
    return {"jobId": jid}


@app.get("/jobs/{jid}/stream")
async def stream(jid: str):
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
    return FileResponse(job.video_path, media_type="video/mp4",
                        filename=job.video_path.name)
