import time
from pathlib import Path

import pytest

from backend.app.db import create_job, get_job, init_db
from backend.app.queue import JobQueue
from backend.app.settings import Settings
from backend.pipeline import runner


def make_settings(tmp_path):
    return Settings(api_key="k", data_dir=tmp_path / "data")


def fake_paper(tmp_path):
    from backend.pipeline.extract import Figure, Paper

    fig = tmp_path / "f.png"
    fig.write_bytes(b"png")
    return Paper(
        arxiv_id="2401.12345",
        title="T",
        full_text="text",
        sections=[],
        figures=[Figure(path=fig, caption="c")],
        warnings=[],
    )


def patch_happy(monkeypatch, tmp_path, n_figures=1, refine_passed=True):
    from backend.pipeline.compiler import CompileResult
    from backend.pipeline.extract import Figure, Paper
    from backend.pipeline.fetch import SourceBundle
    from backend.pipeline.writer import IterationResult

    tex = tmp_path / "paper.tex"
    tex.write_text("\\documentclass{article}x")
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")

    figs = []
    for i in range(n_figures):
        f = tmp_path / f"f{i}.png"
        f.write_bytes(b"png")
        figs.append(Figure(f, f"cap {i}"))

    monkeypatch.setattr(
        runner, "fetch_source", lambda *a, **k: SourceBundle("latex", Path("/t.tar.gz"), [])
    )
    monkeypatch.setattr(
        runner,
        "extract_paper",
        lambda *a, **k: Paper("2401.12345", "T", "text", [], figs, []),
    )
    monkeypatch.setattr(
        runner,
        "select_figures",
        lambda figures, cap=12: figures[:cap],
    )
    monkeypatch.setattr(
        runner, "describe_figures", lambda client, model, figures, **k: {}
    )

    seen = {}
    monkeypatch.setattr(
        runner,
        "write_and_refine",
        lambda client, wm, rm, paper, captions, tp, wd, **k: (
            seen.__setitem__("n_figures", len(paper.figures))
            or (k.get("on_stage") or (lambda s: None))("review")
            or IterationResult(tex, pdf, 3, 1, refine_passed)
        ),
    )
    return tex, pdf, seen


def test_run_job_happy_path(tmp_path, monkeypatch):
    patch_happy(monkeypatch, tmp_path)
    conn = init_db(tmp_path / "db.sqlite")
    s = make_settings(tmp_path)
    jid = create_job(conn, "arxiv.org/abs/2401.12345", "2401.12345", 3, "w", "v")

    runner.run_job(jid, s, conn, client=object())

    job = get_job(conn, jid)
    assert job["status"] == "done"
    assert job["stages"] == ["fetch", "extract", "vision", "draft", "review", "done"]
    assert job["tex_path"] and job["pdf_path"]
    assert job["rounds"] == 1


def test_run_job_caps_figures_passed_to_writer(tmp_path, monkeypatch):
    _, _, seen = patch_happy(monkeypatch, tmp_path, n_figures=14)
    conn = init_db(tmp_path / "db.sqlite")
    s = make_settings(tmp_path)
    jid = create_job(conn, "2401.12345", "2401.12345", 3, "w", "v")

    runner.run_job(jid, s, conn, client=object())

    job = get_job(conn, jid)
    assert job["status"] == "done"
    assert seen["n_figures"] == 12


def test_run_job_review_failed_still_done_with_warning(tmp_path, monkeypatch):
    patch_happy(monkeypatch, tmp_path, refine_passed=False)
    conn = init_db(tmp_path / "db.sqlite")
    s = make_settings(tmp_path)
    jid = create_job(conn, "2401.12345", "2401.12345", 3, "w", "v")

    runner.run_job(jid, s, conn, client=object())

    job = get_job(conn, jid)
    assert job["status"] == "done"
    assert any("reviewer" in w.lower() for w in job["warnings"])


def test_run_job_failure_sets_error(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(runner, "fetch_source", boom)
    conn = init_db(tmp_path / "db.sqlite")
    s = make_settings(tmp_path)
    jid = create_job(conn, "2401.12345", "2401.12345", 4, "w", "v")

    runner.run_job(jid, s, conn, client=object())

    job = get_job(conn, jid)
    assert job["status"] == "failed"
    assert "network down" in job["error"]


def test_submit_runs_job(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "db.sqlite")
    calls = []

    def fake_run(job_id, settings, conn, client=None):
        calls.append(job_id)

    monkeypatch.setattr(runner, "run_job", fake_run)
    s = make_settings(tmp_path)
    q = JobQueue(s, tmp_path / "db.sqlite")
    jid = create_job(conn, "x", "1", 4, "w", "v")
    pos = q.submit(jid)
    assert pos == 1
    q.start()
    deadline = time.time() + 5
    while not calls and time.time() < deadline:
        time.sleep(0.05)
    assert calls == [jid]
