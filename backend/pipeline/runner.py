"""Pipeline orchestration: runs all stages for one job, updating the DB."""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path

from backend.app.db import get_job, update_job
from backend.app.settings import Settings
from backend.pipeline.extract import extract_paper
from backend.pipeline.fetch import fetch_source
from backend.pipeline.vision import describe_figures, select_figures

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
    from backend.pipeline.llm import OpenRouterClient

    job = get_job(conn, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    update_job(conn, job_id, status="running", error=None)
    workdir = Path(settings.data_dir) / f"job_{job_id}"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        if shutil.which("tectonic") is None:
            raise RuntimeError(
                "tectonic not found on PATH — install it to compile PDFs "
                "(see README: Arch `pacman -S tectonic`, macOS `brew install tectonic`, "
                "Windows `scoop install tectonic` or cargo)"
            )
        if client is None:
            client = OpenRouterClient(api_key=settings.api_key)

        _record_stage(conn, job_id, "fetch")
        kind = job.get("source_kind") or "arxiv"
        ref = job["arxiv_id"]
        bundle = fetch_source(kind, ref, workdir / "src")

        _record_stage(conn, job_id, "extract")
        paper = extract_paper(bundle, ref, workdir / "extracted")
        warnings = list(bundle.warnings) + list(paper.warnings)
        update_job(
            conn,
            job_id,
            title=paper.title or job.get("title") or "",
            source_pdf_path=str(bundle.path) if bundle.kind == "pdf" else None,
        )

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
            explanation_level=job.get("explanation_level") or "student",
        )
        captions_path = workdir / "captions.json"
        captions_path.write_text(
            json.dumps(
                {
                    p: c.to_dict() if hasattr(c, "to_dict") else c
                    for p, c in captions.items()
                },
                indent=1,
            )
        )

        if not result.passed:
            warnings.append(
                f"reviewer did not pass after {result.rounds} rounds; output is best-effort"
            )
        warnings.extend(result.notes)
        fields = dict(
            stage="done",
            warnings=warnings,
            tex_path=str(result.tex_path),
            captions_path=str(captions_path),
            rounds=result.rounds,
            pdf_path=str(result.pdf_path) if result.pdf_path else None,
        )
        if result.pdf_path is None:
            # Nothing ever compiled — there is no deliverable. Mark failed so
            # the UI shows an honest error instead of freezing on 'Working'
            # (a done job with pdf_path=None renders as an eternal spinner).
            fields["status"] = "failed"
            fields["error"] = (
                f"no compilable PDF was produced after {result.rounds} review "
                "round(s) — the writer never produced a LaTeX draft that compiles; "
                "the last attempt is saved in the job folder for inspection"
            )
        else:
            fields["status"] = "done"
        cost = getattr(client, "total_cost", None)
        if cost is not None:
            fields["cost_usd"] = round(cost, 6)
        update_job(conn, job_id, **fields)
        _record_stage(conn, job_id, "done")
    except Exception as e:  # noqa: BLE001 — job-level failure boundary
        update_job(conn, job_id, status="failed", error=f"{type(e).__name__}: {e}")
