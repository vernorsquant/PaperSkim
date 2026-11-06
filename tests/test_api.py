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
        config_path=tmp_path / "paperskim.toml",
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
    app = create_app(
        db_path=tmp_path / "db.sqlite",
        data_dir=tmp_path / "data",
        config_path=tmp_path / "paperskim.toml",
        start_queue=False,
    )
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
    import respx

    with respx.mock:
        respx.get("https://openrouter.ai/api/v1/key").respond(
            200, json={"data": {"label": "tests"}}
        )
        put = client.put("/api/settings", json={"api_key": "sk-or-test-abcdef1234567890"})
    assert put.status_code == 200
    assert put.json()["key_status"] == "valid"
    r1 = client.get("/api/settings").json()
    assert r1["has_key"] is True
    assert r1["key_status"] == "valid"
    assert r1["masked"] != "sk-or-test-abcdef1234567890"
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


def test_put_settings_rejects_expired_key(client):
    import respx

    with respx.mock:
        respx.get("https://openrouter.ai/api/v1/key").respond(
            401, json={"error": {"message": "API key expired."}}
        )
        put = client.put("/api/settings", json={"api_key": "dead-key-value"})
    assert put.status_code == 400
    assert "expired" in put.json()["detail"]
    assert client.get("/api/settings").json()["key_status"] == "unchecked"


def test_submit_accepts_doi_input(client):
    r = _submit(client, input="10.1101/2024.01.01.575000")
    assert r.status_code == 200
    assert r.json()["source_kind"] == "doi"
    detail = client.get(f"/api/jobs/{r.json()['id']}").json()
    assert detail["source_kind"] == "doi"
    assert detail["arxiv_id"] == "10.1101/2024.01.01.575000"


def test_submit_accepts_openreview_url(client):
    r = _submit(client, input="https://openreview.net/forum?id=AbC123")
    assert r.status_code == 200
    assert r.json()["source_kind"] == "openreview"


def test_search_endpoint(client):
    import respx

    atom = (
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        '<entry><id>http://arxiv.org/abs/2401.12345</id><title>Found It</title>'
        "<published>2024-02-03T00:00:00Z</published>"
        "<author><name>Ada</name></author></entry></feed>"
    ).encode()
    with respx.mock:
        respx.get("http://export.arxiv.org/api/query").respond(200, content=atom)
        respx.get("https://api.semanticscholar.org/graph/v1/paper/search").respond(
            200, json={"data": []}
        )
        r = client.get("/api/search", params={"q": "found it"})
    assert r.status_code == 200
    rows = r.json()["results"]
    assert rows and rows[0]["kind"] == "arxiv"
    assert rows[0]["ref"] == "2401.12345"


def test_search_short_query_400(client):
    assert client.get("/api/search", params={"q": "x"}).status_code == 400


def test_upload_pdf_job(client):
    r = client.post(
        "/api/jobs/upload",
        files={"file": ("my_paper.pdf", b"%PDF-1.4 fake-upload", "application/pdf")},
        data={"target_pages": "4", "writer_model": "w", "vision_model": "v"},
    )
    assert r.status_code == 200
    assert r.json()["source_kind"] == "upload"
    detail = client.get(f"/api/jobs/{r.json()['id']}").json()
    assert detail["source_kind"] == "upload"


def test_upload_rejects_non_pdf(client):
    r = client.post(
        "/api/jobs/upload",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
        data={"target_pages": "4", "writer_model": "w", "vision_model": "v"},
    )
    assert r.status_code == 400
    assert "PDF" in r.json()["detail"]


def test_source_pdf_served(app, client, tmp_path):
    from backend.app.db import update_job

    pdf = tmp_path / "orig.pdf"
    pdf.write_bytes(b"%PDF-1.4 original")
    jid = _submit(client).json()["id"]
    update_job(app.state.db, jid, source_pdf_path=str(tmp_path / "orig.pdf"))
    resp = client.get(f"/api/jobs/{jid}/source-pdf")
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 original"
    assert client.get("/api/jobs/999/source-pdf").status_code == 404


def test_health_endpoint(client):
    r = client.get("/api/health").json()
    assert set(r) == {"tectonic", "pdftotext", "pdfinfo", "has_key", "key_status"}
    assert r["has_key"] is True
