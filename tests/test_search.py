import httpx
import pytest
import respx

from backend.pipeline import search
from backend.pipeline.search import SearchResult, search_papers

ARXIV_URL = "https://export.arxiv.org/api/query"
S2_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


def _atom_entry(arxiv_id, title, published="2024-01-01T00:00:00Z", authors=("A", "B")):
    authors_xml = "".join(
        f"<author><name>{a}</name></author>" for a in authors
    )
    return (
        f"<entry><id>http://arxiv.org/abs/{arxiv_id}</id>"
        f"<title>{title}</title><published>{published}</published>"
        f"{authors_xml}</entry>"
    )


def _atom(entries):
    return (
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        + "".join(entries)
        + "</feed>"
    ).encode()


def _s2_paper(title, arxiv=None, doi=None, pdf=None, cites=0, year=2024):
    ext = {}
    if arxiv:
        ext["ArXiv"] = arxiv
    if doi:
        ext["DOI"] = doi
    return {
        "title": title,
        "authors": [{"name": n} for n in ("A", "B")],
        "year": year,
        "venue": "Nature",
        "citationCount": cites,
        "externalIds": ext,
        "openAccessPdf": {"url": pdf} if pdf else None,
    }


@respx.mock
def test_merges_and_dedupes_arxiv_and_s2():
    respx.get(ARXIV_URL).respond(
        200, content=_atom([_atom_entry("2401.12345", "Attention Is All You Need Reprise")])
    )
    respx.get(S2_URL).respond(
        200,
        json={
            "data": [
                _s2_paper("Attention Is All You Need Reprise", arxiv="2401.12345", cites=99),
                _s2_paper("Other Paper", doi="10.1000/x", cites=5),
            ]
        },
    )
    out = search_papers("attention", client=httpx.Client())
    assert len(out) == 2
    assert out[0].title == "Attention Is All You Need Reprise"  # most cited wins
    assert out[0].kind == "arxiv"
    assert out[0].origin == "arxiv"  # arXiv row kept, S2 duplicate dropped
    assert out[1].kind == "doi"


@respx.mock
def test_doi_preferred_over_pdf_when_no_arxiv_id():
    respx.get(ARXIV_URL).respond(200, content=_atom([]))
    respx.get(S2_URL).respond(
        200,
        json={"data": [_s2_paper("P", doi="10.1/y", pdf="https://x/p.pdf", cites=3)]},
    )
    out = search_papers("proteins", client=httpx.Client())
    assert out[0].kind == "doi"
    assert out[0].ref == "10.1/y"


@respx.mock
def test_s2_rows_without_refs_are_skipped():
    respx.get(ARXIV_URL).respond(200, content=_atom([]))
    respx.get(S2_URL).respond(
        200, json={"data": [_s2_paper("No ids at all", cites=10)]}
    )
    assert search_papers("no ids", client=httpx.Client()) == []


@respx.mock
def test_both_engines_failing_raises_search_error():
    respx.get(ARXIV_URL).respond(500)
    respx.get(S2_URL).respond(500)
    with pytest.raises(search.SearchError):
        search_papers("query", client=httpx.Client())


@respx.mock
def test_arxiv_failure_alone_still_returns_s2():
    respx.get(ARXIV_URL).respond(500)
    respx.get(S2_URL).respond(
        200, json={"data": [_s2_paper("Survivor", doi="10.2/z")]}
    )
    out = search_papers("query", client=httpx.Client())
    assert len(out) == 1 and out[0].origin == "semantic-scholar"


@respx.mock
def test_default_client_follows_arxiv_redirect():
    # regression: arXiv served over http 301s to https; the default client
    # (no explicit client passed, e.g. via /api/search) must follow it.
    respx.get("http://export.arxiv.org/api/query").respond(
        301, headers={"Location": "https://export.arxiv.org/api/query"}
    )
    respx.get(ARXIV_URL).respond(
        200, content=_atom([_atom_entry("2401.12345", "Redirect Survivor")])
    )
    respx.get(S2_URL).respond(429)
    out = search_papers("redirect")
    assert len(out) == 1 and out[0].origin == "arxiv"


def test_short_query_rejected():
    with pytest.raises(ValueError):
        search_papers("q  ")


def test_dedupe_key_normalizes_arxiv_versions():
    a = SearchResult(title="T", kind="arxiv", ref="2401.1v1")
    b = SearchResult(title="T", kind="arxiv", ref="2401.1v2")
    assert search._dedupe_key(a) == search._dedupe_key(b)
