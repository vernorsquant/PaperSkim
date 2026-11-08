"""FastAPI app factory + routes."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.app.db import (
    create_job,
    fail_orphaned_jobs,
    get_job,
    init_db,
    list_jobs,
    update_job,
)
from backend.app.queue import JobQueue
from backend.app.settings import (
    DEFAULT_CONFIG_PATH,
    Settings,
    load_settings,
    masked_key,
    save_api_key,
    validate_key,
)
from backend.pipeline import pareto, search
from backend.pipeline.sources import resolve_source


class JobRequest(BaseModel):
    input: str
    target_pages: int
    writer_model: str
    vision_model: str


class SettingsRequest(BaseModel):
    api_key: str


UPLOAD_MAX_BYTES = 60 * 1024 * 1024


def _tool_check() -> dict:
    return {
        "tectonic": shutil.which("tectonic") is not None,
        "pdftotext": shutil.which("pdftotext") is not None,
        "pdfinfo": shutil.which("pdfinfo") is not None,
    }


def create_app(
    db_path: Path | None = None,
    data_dir: Path | None = None,
    config_path: Path | None = None,
    start_queue: bool = True,
) -> FastAPI:
    data_dir = data_dir if data_dir is not None else Path("backend/data")
    db_path = db_path if db_path is not None else Path(data_dir) / "jobs.db"
    settings: Settings = load_settings(
        config_path=config_path if config_path is not None else DEFAULT_CONFIG_PATH,
        data_dir=Path(data_dir),
    )
    conn = init_db(db_path)
    fail_orphaned_jobs(conn)
    queue = JobQueue(settings, db_path, max_workers=settings.queue_workers)

    app = FastAPI(title="PaperSkim")
    app.state.settings = settings
    app.state.db = conn
    app.state.queue = queue
    app.state.key_status = "unchecked"

    @app.post("/api/jobs")
    def submit_job(req: JobRequest):
        if not (1 <= req.target_pages <= 30):
            raise HTTPException(400, "target_pages must be between 1 and 30")
        if not req.writer_model or not req.vision_model:
            raise HTTPException(400, "writer_model and vision_model are required")
        if not app.state.settings.api_key:
            raise HTTPException(400, "missing OpenRouter API key (set it in settings)")
        try:
            src = resolve_source(req.input)
        except ValueError as e:
            raise HTTPException(400, str(e))
        jid = create_job(
            conn,
            req.input,
            src.ref,
            req.target_pages,
            req.writer_model,
            req.vision_model,
            source_kind=src.kind,
        )
        position = queue.submit(jid)
        if start_queue:
            queue.start()
        return {"id": jid, "position": position, "source_kind": src.kind}

    @app.post("/api/jobs/upload")
    def upload_job(
        file: UploadFile = File(...),
        target_pages: int = Form(4),
        writer_model: str = Form(...),
        vision_model: str = Form(...),
    ):
        if not (1 <= target_pages <= 30):
            raise HTTPException(400, "target_pages must be between 1 and 30")
        if not writer_model or not vision_model:
            raise HTTPException(400, "writer_model and vision_model are required")
        if not app.state.settings.api_key:
            raise HTTPException(400, "missing OpenRouter API key (set it in settings)")
        data = file.file.read(UPLOAD_MAX_BYTES + 1)
        if len(data) > UPLOAD_MAX_BYTES:
            raise HTTPException(400, "PDF larger than 60 MB")
        if not data.startswith(b"%PDF"):
            raise HTTPException(400, "only PDF files are supported")
        uploads = Path(data_dir) / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex[:12]}_{Path(file.filename or 'paper.pdf').stem[:60]}.pdf"
        path = uploads / name
        path.write_bytes(data)
        jid = create_job(
            conn,
            file.filename or name,
            str(path.resolve()),
            target_pages,
            writer_model,
            vision_model,
            source_kind="upload",
        )
        position = queue.submit(jid)
        if start_queue:
            queue.start()
        return {"id": jid, "position": position, "source_kind": "upload"}

    @app.get("/api/jobs")
    def all_jobs():
        return list_jobs(conn)

    @app.post("/api/queue/stop")
    def stop_queue():
        """Cancel every queued job that has not started; running jobs finish."""
        cancelled = queue.stop()
        return {"cancelled": cancelled, "cancelled_count": len(cancelled)}

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: int):
        job = get_job(conn, job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return job

    @app.get("/api/jobs/{job_id}/pdf")
    def job_pdf(job_id: int):
        job = get_job(conn, job_id)
        if job is None or job["status"] != "done" or not job["pdf_path"]:
            raise HTTPException(404, "PDF not available")
        p = Path(job["pdf_path"])
        if not p.is_file():
            raise HTTPException(404, "PDF file missing")
        return FileResponse(p, media_type="application/pdf")

    @app.get("/api/jobs/{job_id}/latex")
    def job_latex(job_id: int):
        job = get_job(conn, job_id)
        if job is None or job["status"] != "done" or not job["tex_path"]:
            raise HTTPException(404, "LaTeX not available")
        p = Path(job["tex_path"])
        if not p.is_file():
            raise HTTPException(404, "LaTeX file missing")
        return FileResponse(p, media_type="text/x-tex", filename="paper.tex")

    @app.get("/api/jobs/{job_id}/source-pdf")
    def job_source_pdf(job_id: int):
        job = get_job(conn, job_id)
        if job is None or not job.get("source_pdf_path"):
            raise HTTPException(404, "original PDF not available")
        p = Path(job["source_pdf_path"])
        if not p.is_file():
            raise HTTPException(404, "original PDF file missing")
        return FileResponse(p, media_type="application/pdf", filename="original.pdf")

    @app.get("/api/search")
    def search_papers(q: str, limit: int = 10):
        try:
            results = search.search_papers(q, limit=min(max(limit, 1), 25))
        except ValueError as e:
            raise HTTPException(400, str(e))
        except (search.SearchError, httpx.HTTPError) as e:
            raise HTTPException(502, f"paper search failed: {e}")
        return {
            "results": [
                {
                    "title": r.title,
                    "authors": r.authors,
                    "year": r.year,
                    "venue": r.venue,
                    "citations": r.citations,
                    "kind": r.kind,
                    "ref": r.ref,
                    "origin": r.origin,
                }
                for r in results
            ]
        }

    @app.get("/api/models")
    def models(kind: str = "writer"):
        try:
            infos = pareto.fetch_models(app.state.settings.api_key)
        except (httpx.HTTPError, httpx.InvalidURL, ValueError, KeyError, TypeError) as e:
            raise HTTPException(502, f"OpenRouter model list failed: {e}")
        ranked = pareto.rank_models(infos)
        if kind == "vision":
            ranked = [r for r in ranked if r.vision]
        rows = [
            {
                "id": r.id,
                "name": r.name,
                "vision": r.vision,
                "tier": r.tier,
                "prompt_cost": r.prompt_cost,
                "context_length": r.context_length,
            }
            for r in ranked
        ]
        return {"models": rows[:10], "advanced": rows}

    @app.get("/api/settings")
    def get_settings_route():
        return {
            "has_key": bool(app.state.settings.api_key),
            "masked": masked_key(app.state.settings),
            "key_status": app.state.key_status,
        }

    @app.put("/api/settings")
    def put_settings(req: SettingsRequest):
        key = req.api_key.strip()
        if not key:
            raise HTTPException(400, "api_key must not be empty")
        check = validate_key(key)
        if check["status"] in ("expired", "invalid"):
            raise HTTPException(400, check["message"])
        save_api_key(key, config_path=app.state.settings.config_path)
        app.state.settings.api_key = key
        app.state.key_status = check["status"]
        return {"ok": True, "key_status": check["status"], "message": check["message"]}

    @app.get("/api/health")
    def health():
        return {
            **_tool_check(),
            "has_key": bool(app.state.settings.api_key),
            "key_status": app.state.key_status,
        }

    if start_queue:
        queue.start()
    return app


app = create_app()
