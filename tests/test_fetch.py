import gzip
import io
import tarfile

import httpx
import pytest
import respx

from backend.pipeline.fetch import SourceBundle, fetch_source, normalize_arxiv_id


def _make_tar_gz() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"\\documentclass{article}\\begin{document}hi\\end{document}"
        info = tarfile.TarInfo("main.tex")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_normalize_abs_url():
    assert normalize_arxiv_id("https://arxiv.org/abs/2401.12345v2") == "2401.12345v2"


def test_normalize_pdf_url():
    assert normalize_arxiv_id("https://arxiv.org/pdf/2401.12345.pdf") == "2401.12345"


def test_normalize_prefix_form():
    assert normalize_arxiv_id("arXiv:2401.12345") == "2401.12345"


def test_normalize_old_style():
    assert normalize_arxiv_id("cs/0301012") == "cs/0301012"


def test_normalize_bare_id():
    assert normalize_arxiv_id("2401.12345v1") == "2401.12345v1"


def test_normalize_rejects_garbage():
    with pytest.raises(ValueError):
        normalize_arxiv_id("hello world")


def test_normalize_rejects_empty():
    with pytest.raises(ValueError):
        normalize_arxiv_id("")


@respx.mock
def test_fetch_prefers_latex(tmp_path):
    body = _make_tar_gz()
    respx.get("https://export.arxiv.org/e-print/2401.12345").respond(
        200, content=body, headers={"Content-Type": "application/x-eprint-tar"}
    )
    bundle = fetch_source("arxiv", "2401.12345", tmp_path, client=httpx.Client())
    assert bundle.kind == "latex"
    assert bundle.warnings == []
    assert bundle.path.exists()
    assert bundle.path.read_bytes() == body


@respx.mock
def test_fetch_follows_redirect(tmp_path):
    body = _make_tar_gz()
    respx.get("https://export.arxiv.org/e-print/2401.12345").respond(
        301, headers={"Location": "https://export.arxiv.org/src/2401.12345"}
    )
    respx.get("https://export.arxiv.org/src/2401.12345").respond(
        200, content=body, headers={"Content-Type": "application/x-eprint-tar"}
    )
    bundle = fetch_source("arxiv", "2401.12345", tmp_path)
    assert bundle.kind == "latex"


@respx.mock
def test_fetch_falls_back_to_pdf(tmp_path):
    pdf = b"%PDF-1.4 fake"
    respx.get("https://export.arxiv.org/e-print/2401.12345").respond(
        200, content=pdf, headers={"Content-Type": "application/pdf"}
    )
    respx.get("https://export.arxiv.org/pdf/2401.12345").respond(
        200, content=pdf, headers={"Content-Type": "application/pdf"}
    )
    bundle = fetch_source("arxiv", "2401.12345", tmp_path, client=httpx.Client())
    assert isinstance(bundle, SourceBundle)
    assert bundle.kind == "pdf"
    assert len(bundle.warnings) == 1


@respx.mock
def test_fetch_404_falls_back_to_pdf(tmp_path):
    pdf = b"%PDF-1.4 fake"
    respx.get("https://export.arxiv.org/e-print/9999.99999").respond(404)
    respx.get("https://export.arxiv.org/pdf/9999.99999").respond(
        200, content=pdf, headers={"Content-Type": "application/pdf"}
    )
    bundle = fetch_source("arxiv", "9999.99999", tmp_path, client=httpx.Client())
    assert bundle.kind == "pdf"
    assert bundle.warnings


@respx.mock
def test_fetch_bare_tex_source(tmp_path):
    tex = b"\\documentclass{article}\\begin{document}single file\\end{document}"
    respx.get("https://export.arxiv.org/e-print/2401.12345").respond(
        200, content=tex, headers={"Content-Type": "application/x-eprint"}
    )
    bundle = fetch_source("arxiv", "2401.12345", tmp_path, client=httpx.Client())
    assert bundle.kind == "latex"
    assert b"single file" in bundle.path.read_bytes()


@respx.mock
def test_fetch_pdf_url_downloads_local(tmp_path):
    respx.get("https://example.com/paper.pdf").respond(
        200, content=b"%PDF-1.4 fake", headers={"Content-Type": "application/pdf"}
    )
    bundle = fetch_source("pdf_url", "https://example.com/paper.pdf", tmp_path, client=httpx.Client())
    assert bundle.kind == "pdf"
    assert bundle.path.read_bytes() == b"%PDF-1.4 fake"
    assert bundle.path.parent == tmp_path


@respx.mock
def test_fetch_pdf_url_rejects_html_paywall(tmp_path):
    respx.get("https://example.com/paper").respond(
        200, content=b"<!DOCTYPE html><html>login required</html>"
    )
    with pytest.raises(ValueError, match="HTML"):
        fetch_source("pdf_url", "https://example.com/paper", tmp_path, client=httpx.Client())


@respx.mock
def test_fetch_acl_builds_pdf_url(tmp_path):
    respx.get("https://aclanthology.org/D19-1001.pdf").respond(
        200, content=b"%PDF-1.4 acl"
    )
    bundle = fetch_source("acl", "D19-1001", tmp_path, client=httpx.Client())
    assert bundle.kind == "pdf"
    assert bundle.path.read_bytes() == b"%PDF-1.4 acl"


@respx.mock
def test_fetch_openreview_builds_pdf_url(tmp_path):
    respx.get("https://openreview.net/pdf?id=AbC123").respond(
        200, content=b"%PDF-1.4 or"
    )
    bundle = fetch_source("openreview", "AbC123", tmp_path, client=httpx.Client())
    assert bundle.kind == "pdf"


@respx.mock
def test_fetch_doi_upgrades_to_arxiv_latex(tmp_path):
    body = _make_tar_gz()
    respx.get("https://api.openalex.org/works/https%3A%2F%2Fdoi.org%2F10.48550%2FarXiv.2401.12345").respond(
        200,
        json={
            "title": "T",
            "locations": [
                {"source": {"landing_page_url": "https://arxiv.org/abs/2401.12345"},
                 "pdf_url": None}
            ],
        },
    )
    respx.get("https://export.arxiv.org/e-print/2401.12345").respond(
        200, content=body, headers={"Content-Type": "application/x-eprint-tar"}
    )
    bundle = fetch_source("doi", "10.48550/arXiv.2401.12345", tmp_path, client=httpx.Client())
    assert bundle.kind == "latex"
    assert any("resolved to arXiv" in w for w in bundle.warnings)


@respx.mock
def test_fetch_doi_uses_best_oa_pdf(tmp_path):
    respx.get("https://api.openalex.org/works/https%3A%2F%2Fdoi.org%2F10.1101%2F2024.01.01.575000").respond(
        200,
        json={
            "title": "Bio paper",
            "locations": [],
            "best_oa_location": {"pdf_url": "https://example.com/bio.pdf"},
        },
    )
    respx.get("https://example.com/bio.pdf").respond(200, content=b"%PDF-1.4 bio")
    bundle = fetch_source("doi", "10.1101/2024.01.01.575000", tmp_path, client=httpx.Client())
    assert bundle.kind == "pdf"
    assert any("OpenAlex" in w for w in bundle.warnings)


@respx.mock
def test_fetch_doi_no_oa_raises(tmp_path):
    respx.get("https://api.openalex.org/works/https%3A%2F%2Fdoi.org%2F10.9999%2Fpaywall").respond(
        200, json={"title": "Paywalled", "locations": [], "best_oa_location": None}
    )
    with pytest.raises(ValueError, match="no open-access PDF"):
        fetch_source("doi", "10.9999/paywall", tmp_path, client=httpx.Client())


@respx.mock
def test_fetch_s2_upgrades_to_arxiv(tmp_path):
    body = _make_tar_gz()
    respx.get("https://api.semanticscholar.org/graph/v1/paper/" + "a" * 40).respond(
        200, json={"externalIds": {"ArXiv": "2401.12345"}, "openAccessPdf": None}
    )
    respx.get("https://export.arxiv.org/e-print/2401.12345").respond(
        200, content=body, headers={"Content-Type": "application/x-eprint-tar"}
    )
    bundle = fetch_source("s2", "a" * 40, tmp_path, client=httpx.Client())
    assert bundle.kind == "latex"


@respx.mock
def test_fetch_s2_no_pdf_raises(tmp_path):
    respx.get("https://api.semanticscholar.org/graph/v1/paper/" + "b" * 40).respond(
        200, json={"externalIds": {}, "openAccessPdf": None}
    )
    with pytest.raises(ValueError, match="no open-access PDF"):
        fetch_source("s2", "b" * 40, tmp_path, client=httpx.Client())


def test_fetch_upload_copies_local_pdf(tmp_path):
    upload = tmp_path / "uploads" / "x.pdf"
    upload.parent.mkdir()
    upload.write_bytes(b"%PDF-1.4 upload")
    bundle = fetch_source("upload", str(upload), tmp_path / "src")
    assert bundle.kind == "pdf"
    assert bundle.path.exists()
    assert bundle.path.read_bytes() == b"%PDF-1.4 upload"
