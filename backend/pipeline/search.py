"""Paper search: arXiv Atom API + Semantic Scholar graph API, merged and deduped."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import httpx

ARXIV_SEARCH_URL = "https://export.arxiv.org/api/query"
S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "title,authors,year,venue,citationCount,externalIds,openAccessPdf"

_ATOM = "{http://www.w3.org/2005/Atom}"


class SearchError(RuntimeError):
    pass


@dataclass
class SearchResult:
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    citations: int | None = None
    kind: str = ""  # "arxiv" | "doi" | "pdf_url"
    ref: str = ""
    origin: str = ""  # which search engine found it


_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "")).strip()


def _search_arxiv(query: str, limit: int, client: httpx.Client) -> list[SearchResult]:
    r = client.get(
        ARXIV_SEARCH_URL,
        params={
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
        },
    )
    r.raise_for_status()
    out: list[SearchResult] = []
    root = ET.fromstring(r.content)
    from backend.pipeline.fetch import normalize_arxiv_id

    for entry in root.findall(f"{_ATOM}entry"):
        raw_id = _clean(entry.findtext(f"{_ATOM}id") or "")
        try:
            arxiv_id = normalize_arxiv_id(raw_id)
        except ValueError:
            continue
        authors = [
            _clean(a.findtext(f"{_ATOM}name") or "")
            for a in entry.findall(f"{_ATOM}author")
        ]
        published = _clean(entry.findtext(f"{_ATOM}published") or "")
        out.append(
            SearchResult(
                title=_clean(entry.findtext(f"{_ATOM}title") or ""),
                authors=[a for a in authors if a],
                year=int(published[:4]) if published[:4].isdigit() else None,
                venue="arXiv",
                citations=None,
                kind="arxiv",
                ref=arxiv_id,
                origin="arxiv",
            )
        )
    return out


def _s2_ref(paper: dict) -> tuple[str, str] | None:
    ext = paper.get("externalIds") or {}
    arxiv_id = ext.get("ArXiv")
    if arxiv_id:
        return "arxiv", str(arxiv_id)
    doi = ext.get("DOI")
    if doi:
        return "doi", str(doi)
    url = (paper.get("openAccessPdf") or {}).get("url")
    if url:
        return "pdf_url", str(url)
    return None


def _search_s2(query: str, limit: int, client: httpx.Client) -> list[SearchResult]:
    r = client.get(
        S2_SEARCH_URL,
        params={"query": query, "limit": limit, "fields": S2_FIELDS},
    )
    r.raise_for_status()
    out: list[SearchResult] = []
    for paper in r.json().get("data") or []:
        ref = _s2_ref(paper)
        if ref is None:
            continue  # not reliably submittable
        year = paper.get("year")
        cites = paper.get("citationCount")
        out.append(
            SearchResult(
                title=_clean(paper.get("title") or ""),
                authors=[
                    _clean((a or {}).get("name") or "")
                    for a in (paper.get("authors") or [])
                ],
                year=int(year) if year else None,
                venue=_clean(paper.get("venue") or ""),
                citations=int(cites) if cites is not None else None,
                kind=ref[0],
                ref=ref[1],
                origin="semantic-scholar",
            )
        )
    return out


def _dedupe_key(r: SearchResult) -> str:
    if r.kind == "arxiv":
        new = r.ref.split("v")[0] if "v" in r.ref and r.ref[0].isdigit() else r.ref
        return f"arxiv:{new}"
    if r.kind == "doi":
        return f"doi:{r.ref.lower()}"
    return f"title:{re.sub(r'[^a-z0-9]+', '', r.title.lower())}"


def search_papers(query: str, limit: int = 10, client: httpx.Client | None = None) -> list[SearchResult]:
    query = (query or "").strip()
    if len(query) < 2:
        raise ValueError("search query too short")
    own = client is None
    c = client if client is not None else httpx.Client(timeout=30, follow_redirects=True)
    errors: list[str] = []
    results: list[SearchResult] = []
    try:
        try:
            results += _search_arxiv(query, limit, c)
        except Exception as e:  # noqa: BLE001 — one engine failing must not kill search
            errors.append(f"arXiv search failed: {e}")
        try:
            results += _search_s2(query, limit, c)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Semantic Scholar search failed: {e}")
    finally:
        if own:
            c.close()
    if not results:
        if errors:
            raise SearchError("; ".join(errors))
        return []
    # group with arXiv-origin rows winning identity (LaTeX pipeline), merging
    # missing display fields from the dropped duplicates
    groups: dict[str, SearchResult] = {}
    for r in results:
        key = _dedupe_key(r)
        cur = groups.get(key)
        if cur is None:
            groups[key] = r
            continue
        if cur.origin != "arxiv" and r.origin == "arxiv":
            r = _merge_rows(r, cur)
            groups[key] = r
        else:
            _merge_rows(cur, r)
    unique = sorted(
        groups.values(),
        key=lambda r: (-(r.citations or 0), -(r.year or 0), r.title.lower()),
    )
    return unique[: limit * 2]


def _merge_rows(winner: SearchResult, loser: SearchResult) -> SearchResult:
    if winner.citations is None and loser.citations is not None:
        winner.citations = loser.citations
    if winner.year is None and loser.year is not None:
        winner.year = loser.year
    if not winner.venue and loser.venue:
        winner.venue = loser.venue
    return winner
