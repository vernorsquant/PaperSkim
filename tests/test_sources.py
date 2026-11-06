import pytest

from backend.pipeline.sources import resolve_source


def test_arxiv_abs_url():
    assert resolve_source("https://arxiv.org/abs/2401.12345").kind == "arxiv"
    assert resolve_source("https://arxiv.org/abs/2401.12345").ref == "2401.12345"


def test_arxiv_bare_id():
    assert resolve_source("2401.12345v2").ref == "2401.12345v2"


def test_arxiv_prefix():
    assert resolve_source("arXiv: 1706.03762").ref == "1706.03762"


def test_bare_doi():
    r = resolve_source("10.1000/journal.2024.12345")
    assert r.kind == "doi"
    assert r.ref == "10.1000/journal.2024.12345"


def test_doi_url():
    r = resolve_source("https://doi.org/10.1000/journal.123")
    assert r.kind == "doi"
    assert r.ref == "10.1000/journal.123"


def test_dx_doi_url_with_trailing_slash():
    r = resolve_source("http://dx.doi.org/10.1000/xyz/")
    assert r.kind == "doi"
    assert r.ref == "10.1000/xyz"


def test_arxiv_doi_upgrades_to_latex():
    r = resolve_source("10.48550/arXiv.2401.12345")
    assert r.kind == "arxiv"
    assert r.ref == "2401.12345"


def test_biorxiv_url_extracts_doi():
    r = resolve_source("https://www.biorxiv.org/content/10.1101/2024.01.01.575000v1.full")
    assert r.kind == "doi"
    assert r.ref == "10.1101/2024.01.01.575000"


def test_medrxiv_url_extracts_doi():
    r = resolve_source("https://www.medrxiv.org/content/10.1101/2023.05.05.123456.full.pdf")
    assert r.kind == "doi"
    assert r.ref == "10.1101/2023.05.05.123456"


def test_acl_url():
    r = resolve_source("https://aclanthology.org/2024.acl-long.123/")
    assert r.kind == "acl"
    assert r.ref == "2024.acl-long.123"


def test_acl_pdf_url():
    r = resolve_source("https://aclanthology.org/D19-1001.pdf")
    assert r.kind == "acl"
    assert r.ref == "D19-1001"


def test_openreview_forum_url():
    r = resolve_source("https://openreview.net/forum?id=AbCdEf123")
    assert r.kind == "openreview"
    assert r.ref == "AbCdEf123"


def test_openreview_pdf_url():
    r = resolve_source("https://openreview.net/pdf?id=XyZ_9-q")
    assert r.kind == "openreview"
    assert r.ref == "XyZ_9-q"


def test_s2_paper_url_with_slug():
    sha = "a" * 40
    r = resolve_source(f"https://www.semanticscholar.org/paper/some-title-here/{sha}")
    assert r.kind == "s2"
    assert r.ref == sha


def test_s2_paper_url_bare_sha():
    sha = "b" * 40
    r = resolve_source(f"https://semanticscholar.org/paper/{sha}")
    assert r.kind == "s2"
    assert r.ref == sha


def test_direct_pdf_url():
    url = "https://example.com/papers/deep-learning.pdf"
    r = resolve_source(url)
    assert r.kind == "pdf_url"
    assert r.ref == url


def test_plain_https_url_fallback():
    url = "https://example.com/whatever"
    r = resolve_source(url)
    assert r.kind == "pdf_url"


def test_garbage_rejected():
    with pytest.raises(ValueError):
        resolve_source("not a paper at all !!")


def test_empty_rejected():
    with pytest.raises(ValueError):
        resolve_source("   ")
