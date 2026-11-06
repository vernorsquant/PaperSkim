import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.pipeline import pareto

MODELS_URL = "https://openrouter.ai/api/v1/models"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123456")
    return create_app(
        db_path=tmp_path / "db.sqlite",
        data_dir=tmp_path / "data",
        start_queue=False,
    )


@pytest.fixture
def client(app):
    return TestClient(app)


def _submit(client, **over):
    body = {
        "input": "arxiv.org/abs/2401.12345",
        "target_pages": 4,
        "writer_model": "w",
        "vision_model": "v",
    }
    body.update(over)
    return client.post("/api/jobs", json=body)


def test_submit_rejects_missing_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    app = create_app(db_path=tmp_path / "db.sqlite", data_dir=tmp_path / "data")
    c = TestClient(app)
    r = _submit(c)
    assert r.status_code == 400
    assert "key" in r.json()["detail"].lower()


def test_submit_rejects_bad_pages(client):
    assert _submit(client, target_pages=0).status_code == 400
    assert _submit(client, target_pages=31).status_code == 400


def test_submit_rejects_bad_input(client):
    r = _submit(client, input="not an arxiv id at all !!")
    assert r.status_code == 400


def test_submit_ok_enqueues(client):
    r = _submit(client)
    assert r.status_code == 200
    assert r.json()["id"] >= 1
    assert r.json()["position"] == 1


def test_get_models_writer_vs_vision(client, monkeypatch):
    monkeypatch.setattr(pareto, "_CACHE", None)
    api_model = lambda id, image: {
        "id": id,
        "name": id,
        "pricing": {"prompt": "0.000001"},
        "architecture": {"input_modalities": ["text"] + (["image"] if image else [])},
    }
    with __import__("respx").mock:
        __import__("respx").get(MODELS_URL).respond(
            200,
            json={"data": [api_model("text-only", False), api_model("seer", True)]},
        )
        writer = client.get("/api/models?kind=writer").json()
        vision = client.get("/api/models?kind=vision").json()
    ids_writer = {m["id"] for m in writer["models"]}
    ids_vision = {m["id"] for m in vision["models"]}
    assert ids_vision <= ids_writer
    assert "seer" in ids_vision
    assert "text-only" not in ids_vision


def test_models_502_on_openrouter_failure(client, monkeypatch):
    monkeypatch.setattr(pareto, "_CACHE", None)
    import respx

    with respx.mock:
        respx.get(MODELS_URL).respond(500)
        r = client.get("/api/models?kind=writer")
    assert r.status_code == 502


def test_settings_mask_roundtrip(client):
    r0 = client.get("/api/settings").json()
    assert r0["has_key"] is True  # env-provided key
    assert r0["masked"] != "test-key-123456"
    put = client.put("/api/settings", json={"api_key": "sk-or-abcdef1234567890"})
    assert put.status_code == 200
    r1 = client.get("/api/settings").json()
    assert r1["has_key"] is True
    assert r1["masked"] != "sk-or-abcdef1234567890"
    assert "****" in r1["masked"]


def test_pdf_404_before_done(client):
    r = _submit(client)
    jid = r.json()["id"]
    assert client.get(f"/api/jobs/{jid}/pdf").status_code == 404


def test_pdf_served_after_done(client, app, tmp_path):
    r = _submit(client)
    jid = r.json()["id"]
    pdf = tmp_path / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    from backend.app.db import update_job

    update_job(app.state.db, jid, status="done", pdf_path=str(pdf))
    resp = client.get(f"/api/jobs/{jid}/pdf")
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 fake"


def test_get_job_detail(client):
    r = _submit(client)
    jid = r.json()["id"]
    detail = client.get(f"/api/jobs/{jid}").json()
    assert detail["arxiv_id"] == "2401.12345"
    assert detail["stages"] == []
    jobs = client.get("/api/jobs").json()
    assert jobs[0]["id"] == jid
