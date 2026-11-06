"""FastAPI app factory + routes."""

from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.app.db import create_job, get_job, init_db, list_jobs, update_job
from backend.app.queue import JobQueue
from backend.app.settings import (
    DEFAULT_CONFIG_PATH,
    load_settings,
    masked_key,
    save_api_key,
)
from backend.pipeline.fetch import normalize_arxiv_id
from backend.pipeline.pareto import fetch_models, rank_models


class JobRequest(BaseModel):
    input: str
    target_pages: int
    writer_model: str
    vision_model: str


class SettingsRequest(BaseModel):
    api_key: str


def create_app(
    db_path: Path | None = None,
    data_dir: Path | None = None,
    config_path: Path | None = None,
    start_queue: bool = True,
) -> FastAPI:
    data_dir = data_dir if data_dir is not None else Path("backend/data")
    db_path = db_path if db_path is not None else Path(data_dir) / "jobs.db"
    settings = load_settings(
        config_path=config_path if config_path is not None else DEFAULT_CONFIG_PATH,
        data_dir=Path(data_dir),
    )
    conn = init_db(db_path)
    queue = JobQueue(settings, db_path)

    app = FastAPI(title="PaperSkim")
    app.state.settings = settings
    app.state.db = conn
    app.state.queue = queue

    @app.post("/api/jobs")
    def submit_job(req: JobRequest):
        if not (1 <= req.target_pages <= 30):
            raise HTTPException(400, "target_pages must be between 1 and 30")
        if not req.writer_model or not req.vision_model:
            raise HTTPException(400, "writer_model and vision_model are required")
        if not app.state.settings.api_key:
            raise HTTPException(400, "missing OpenRouter API key (set it in settings)")
        try:
            arxiv_id = normalize_arxiv_id(req.input)
        except ValueError as e:
            raise HTTPException(400, str(e))
        jid = create_job(
            conn,
            req.input,
            arxiv_id,
            req.target_pages,
            req.writer_model,
            req.vision_model,
        )
        position = queue.submit(jid)
        if start_queue:
            queue.start()
        return {"id": jid, "position": position}

    @app.get("/api/jobs")
    def all_jobs():
        return list_jobs(conn)

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

    @app.get("/api/models")
    def models(kind: str = "writer"):
        try:
            infos = fetch_models(app.state.settings.api_key)
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            raise HTTPException(502, f"OpenRouter model list failed: {e}")
        ranked = rank_models(infos)
        if kind == "vision":
            ranked = [r for r in ranked if r.vision]
        rows = [
            {
                "id": r.id,
                "name": r.name,
                "vision": r.vision,
                "tier": r.tier,
                "prompt_cost": r.prompt_cost,
            }
            for r in ranked
        ]
        return {"models": rows[:10], "advanced": rows}

    @app.get("/api/settings")
    def get_settings_route():
        return {"has_key": bool(app.state.settings.api_key), "masked": masked_key(app.state.settings)}

    @app.put("/api/settings")
    def put_settings(req: SettingsRequest):
        if not req.api_key.strip():
            raise HTTPException(400, "api_key must not be empty")
        save_api_key(req.api_key.strip(), config_path=app.state.settings.config_path)
        app.state.settings.api_key = req.api_key.strip()
        return {"ok": True}

    if start_queue:
        queue.start()
    return app


app = create_app()
