import json
import logging
import os
from pathlib import Path
import queue
import sqlite3
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .engine import Engine, MODELS, hardware
from .formats import format_transcript

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("STT_DATA_DIR", ROOT.parent / "data")).resolve()
MAX_BYTES = int(os.environ.get("STT_MAX_UPLOAD_MB", "500")) * 1024 * 1024
EXTENSIONS = {".mp3", ".wav", ".m4a", ".mp4", ".aac", ".ogg", ".opus", ".flac", ".webm", ".aiff", ".aif", ".wma"}
log = logging.getLogger(__name__)


class Store:
    def __init__(self, root):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db = root / "transcripts.sqlite3"
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db, timeout=30)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def get(self, job_id):
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Přepis nebyl nalezen.")
        return json.loads(row[0])

    def put(self, item):
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO jobs VALUES (?,?)", (item["id"], json.dumps(item)))

    def all(self):
        with self.connect() as conn:
            return sorted((json.loads(r[0]) for r in conn.execute("SELECT payload FROM jobs")),
                          key=lambda j: j["created"], reverse=True)

    def update(self, job_id, **changes):
        item = self.get(job_id)
        item.update(changes)
        self.put(item)


def work(app):
    while True:
        entry = app.state.queue.get()
        if entry is None:
            return
        job_id, path = entry
        try:
            job = app.state.store.get(job_id)
            result = app.state.engine.transcribe(
                path, job["model"], job["requested_device"], job["language"], job["prompt"],
                lambda **kw: app.state.store.update(job_id, **kw),
            )
            path.unlink(missing_ok=True)
            app.state.store.update(job_id, **result, status="done", progress=100)
        except Exception as exc:
            log.exception("Transcription failed: %s", job_id)
            path.unlink(missing_ok=True)
            app.state.store.update(job_id, status="error", error=f"{type(exc).__name__}: {exc}"[:1200])
        finally:
            path.unlink(missing_ok=True)
            app.state.slots.release()
            app.state.queue.task_done()


@asynccontextmanager
async def lifespan(app):
    app.state.store = Store(DATA)
    uploads = DATA / "uploads"
    uploads.mkdir(exist_ok=True)
    # This app runs with ONE server process; interrupted jobs are never silently lost.
    for item in app.state.store.all():
        if item["status"] not in ("done", "error"):
            app.state.store.update(item["id"], status="error", error="Server byl restartován. Nahrajte soubor znovu.")
    for path in uploads.glob("*"):
        if path.is_file():
            path.unlink()
    app.state.engine = Engine(DATA / "models")
    app.state.queue = queue.Queue()
    app.state.slots = threading.BoundedSemaphore(8)
    worker = threading.Thread(target=work, args=(app,), daemon=True)
    worker.start()
    yield
    app.state.queue.put(None)


app = FastAPI(title="STT AI", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])


@app.middleware("http")
async def local_requests(request: Request, call_next):
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse({"detail": "Požadavek z jiné stránky není povolen."}, status_code=403)
    # Reject oversized requests before multipart parsing when Content-Length is present.
    length = request.headers.get("content-length")
    if length and (not length.isdigit() or int(length) > MAX_BYTES + 1024 * 1024):
        return JSONResponse({"detail": "Soubor překračuje limit velikosti."}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/info")
def info():
    return {"hardware": hardware(), "models": MODELS, "max_upload_mb": MAX_BYTES // (1024 * 1024)}


@app.get("/api/jobs")
def jobs():
    return [{k: v for k, v in j.items() if k not in ("segments", "prompt")}
            for j in app.state.store.all()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return app.state.store.get(job_id)


@app.post("/api/jobs", status_code=202)
async def upload(file: UploadFile = File(...),
                 model: Literal["tiny", "base", "small", "medium", "large-v3", "turbo"] = Form("small"),
                 device: Literal["auto", "cpu", "cuda", "mlx"] = Form("auto"),
                 language: Literal["cs", "sk", "en", "de", "pl", "uk", "auto"] = Form("cs"),
                 prompt: str = Form("", max_length=1000)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in EXTENSIONS:
        raise HTTPException(415, "Nepodporovaný formát. Vyberte audio nebo video soubor.")
    if not app.state.slots.acquire(blocking=False):
        raise HTTPException(429, "Fronta je plná (8 souborů). Počkejte na dokončení přepisu.")
    job_id = uuid4().hex
    path = DATA / "uploads" / f"{job_id}{suffix}"
    accepted = False
    try:
        total = 0
        with path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise HTTPException(413, "Soubor překračuje limit velikosti.")
                out.write(chunk)
        if total == 0:
            raise HTTPException(400, "Soubor je prázdný.")
        job = {"id": job_id, "filename": (file.filename or "audio")[:255], "created": time.time(),
               "status": "queued", "progress": 0, "model": model, "requested_device": device,
               "language": "" if language == "auto" else language, "prompt": prompt,
               "segments": [], "error": None}
        app.state.store.put(job)
        app.state.queue.put((job_id, path))
        accepted = True
        return job
    finally:
        await file.close()
        if not accepted:
            path.unlink(missing_ok=True)
            app.state.slots.release()


class Segment(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(ge=0, allow_inf_nan=False)
    text: str = Field(max_length=10000)

    @model_validator(mode="after")
    def valid_time(self):
        if self.end < self.start:
            raise ValueError("Konec musí následovat po začátku.")
        return self


class Edit(BaseModel):
    segments: list[Segment] = Field(max_length=100000)


@app.put("/api/jobs/{job_id}")
def edit_job(job_id: str, body: Edit):
    job = app.state.store.get(job_id)
    if job["status"] != "done":
        raise HTTPException(409, "Přepis ještě není dokončen.")
    app.state.store.update(job_id, segments=[s.model_dump() for s in body.segments])
    return {"ok": True}


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str):
    job = app.state.store.get(job_id)
    if job["status"] not in ("done", "error"):
        raise HTTPException(409, "Probíhající přepis nelze smazat.")
    with app.state.store.connect() as conn:
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    return Response(status_code=204)


@app.get("/api/jobs/{job_id}/export/{fmt}")
def export(job_id: str, fmt: Literal["txt", "srt", "vtt", "json"]):
    job = app.state.store.get(job_id)
    if job["status"] != "done":
        raise HTTPException(409, "Přepis ještě není dokončen.")
    content = format_transcript(job, fmt)
    return Response(content, media_type="application/json" if fmt == "json" else "text/plain",
                    headers={"Content-Disposition": f'attachment; filename="prepis-{job_id[:8]}.{fmt}"'})


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
