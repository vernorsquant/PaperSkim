"""Pipeline orchestration: runs all stages for one job, updating the DB."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from backend.app.db import update_job
from backend.app.settings import Settings
from backend.pipeline.extract import extract_paper
from backend.pipeline.fetch import fetch_source, normalize_arxiv_id
from backend.pipeline.vision import describe_figures, select_figures
from dataclasses import replace

from backend.pipeline.writer import write_and_refine


def _record_stage(conn: sqlite3.Connection, job_id: int, stage: str) -> None:
    job = conn.execute("SELECT stages FROM jobs WHERE id = ?", (job_id,)).fetchone()
    stages = json.loads(job["stages"] or "[]")
    stages.append(stage)
    update_job(conn, job_id, stage=stage, stages=stages)


def run_job(
    job_id: int,
    settings: Settings,
    conn: sqlite3.Connection,
    client=None,
) -> None:
    from backend.app.db import get_job
    from backend.pipeline.llm import OpenRouterClient

    job = get_job(conn, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    update_job(conn, job_id, status="running", error=None)
    workdir = Path(settings.data_dir) / f"job_{job_id}"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        if client is None:
            client = OpenRouterClient(api_key=settings.api_key)

        _record_stage(conn, job_id, "fetch")
        arxiv_id = normalize_arxiv_id(job["arxiv_input"])
        bundle = fetch_source(arxiv_id, workdir / "src")

        _record_stage(conn, job_id, "extract")
        paper = extract_paper(bundle, arxiv_id, workdir / "extracted")
        warnings = list(bundle.warnings) + list(paper.warnings)

        _record_stage(conn, job_id, "vision")
        selected = select_figures(paper.figures)
        captions = (
            describe_figures(client, job["vision_model"], selected, warnings=warnings)
            if selected
            else {}
        )
        if warnings:
            update_job(conn, job_id, warnings=warnings)

        _record_stage(conn, job_id, "draft")
        active_paper = replace(paper, figures=selected)
        result = write_and_refine(
            client,
            job["writer_model"],
            job["writer_model"],
            active_paper,
            captions,
            job["target_pages"],
            workdir,
            on_stage=lambda s: _record_stage(conn, job_id, s),
        )
        captions_path = workdir / "captions.json"
        captions_path.write_text(json.dumps(captions, indent=1))

        if not result.passed:
            warnings.append(
                f"reviewer did not pass after {result.rounds} rounds; output is best-effort"
            )
        update_job(
            conn,
            job_id,
            status="done",
            stage="done",
            warnings=warnings,
            pdf_path=str(result.pdf_path) if result.pdf_path else None,
            tex_path=str(result.tex_path),
            captions_path=str(captions_path),
            rounds=result.rounds,
        )
        _record_stage(conn, job_id, "done")
    except Exception as e:  # noqa: BLE001 — job-level failure boundary
        update_job(conn, job_id, status="failed", error=f"{type(e).__name__}: {e}")
