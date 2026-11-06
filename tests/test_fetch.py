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
    bundle = fetch_source("2401.12345", tmp_path, client=httpx.Client())
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
    bundle = fetch_source("2401.12345", tmp_path)
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
    bundle = fetch_source("2401.12345", tmp_path, client=httpx.Client())
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
    bundle = fetch_source("9999.99999", tmp_path, client=httpx.Client())
    assert bundle.kind == "pdf"
    assert bundle.warnings


@respx.mock
def test_fetch_bare_tex_source(tmp_path):
    tex = b"\\documentclass{article}\\begin{document}single file\\end{document}"
    respx.get("https://export.arxiv.org/e-print/2401.12345").respond(
        200, content=tex, headers={"Content-Type": "application/x-eprint"}
    )
    bundle = fetch_source("2401.12345", tmp_path, client=httpx.Client())
    assert bundle.kind == "latex"
    assert b"single file" in bundle.path.read_bytes()
