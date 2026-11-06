"""Input source download: arXiv LaTeX (preferred), open-access PDFs for everything else."""

from __future__ import annotations

import re
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import httpx

EPRINT_URL = "https://export.arxiv.org/e-print"
PDF_URL = "https://export.arxiv.org/pdf"

S2_API = "https://api.semanticscholar.org/graph/v1/paper"
OPENALEX_API = "https://api.openalex.org/works"

_NEW_STYLE = re.compile(r"\d{4}\.\d{4,5}(v\d+)?")
_OLD_STYLE = re.compile(r"[a-z\-]+(\.[A-Za-z]{2})?/\d{7}")
_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/([^\s/?#]+?)(?:\.pdf)?$", re.IGNORECASE)
_PREFIX = re.compile(r"^arxiv:\s*(.+)$", re.IGNORECASE)

PDF_FALLBACK_WARNING = "no LaTeX source available; PDF fallback (text-only, no figures)"


@dataclass
class SourceBundle:
    kind: str  # "latex" | "pdf"
    path: Path
    warnings: list[str] = field(default_factory=list)


def normalize_arxiv_id(s: str) -> str:
    s = s.strip()
    if not s:
        raise ValueError("empty arXiv input")
    m = _URL.search(s)
    if m:
        candidate = m.group(1)
    else:
        m = _PREFIX.match(s)
        candidate = m.group(1).strip() if m else s
    candidate = candidate.strip()
    if _NEW_STYLE.fullmatch(candidate) or _OLD_STYLE.fullmatch(candidate):
        return candidate
    raise ValueError(f"unrecognized arXiv id: {s!r}")


def _safe_name(ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", ref)[:120]


def _arxiv_id_from_url(url: str) -> str | None:
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([^\s/?#]+?)(?:\.pdf)?[?#].*$|"
                  r"arxiv\.org/(?:abs|pdf)/([^\s/?#]+?)(?:\.pdf)?/?$", url, re.IGNORECASE)
    if not m:
        return None
    candidate = m.group(1) or m.group(2)
    if candidate and (_NEW_STYLE.fullmatch(candidate) or _OLD_STYLE.fullmatch(candidate)):
        return candidate
    return None


def _download_pdf(
    url: str, dest_dir: Path, name: str, client: httpx.Client, warnings: list[str]
) -> SourceBundle:
    r = client.get(url)
    r.raise_for_status()
    head = r.content[:1024].lstrip()
    if head.startswith(b"<!DOCTYPE") or head.startswith(b"<html"):
        raise ValueError(
            f"that link served an HTML page, not a PDF (paywall?) — {url}. "
            "Try a direct open-access PDF link instead."
        )
    if not head.startswith(b"%PDF"):
        raise ValueError(f"that link did not return a PDF ({url})")
    path = dest_dir / f"{_safe_name(name)}.pdf"
    path.write_bytes(r.content)
    return SourceBundle(kind="pdf", path=path, warnings=warnings)


def _resolve_doi_pdf_url(
    doi: str, client: httpx.Client
) -> tuple[str, str, list[str]]:  # (kind, ref_or_url, warnings)
    """OpenAlex: find an open-access PDF for a DOI (works for bioRxiv/medRxiv too)."""
    r = client.get(
        f"{OPENALEX_API}/https://doi.org/{quote(doi, safe='')}",
        params={"mailto": "paperskim@localhost"},
    )
    if r.status_code == 404:
        raise ValueError(f"DOI not found in OpenAlex: {doi}")
    r.raise_for_status()
    work = r.json()
    title = str(work.get("title") or "")

    # arXiv upgrade: any location pointing at arXiv gets the LaTeX pipeline
    for loc in work.get("locations") or []:
        landing = str(((loc.get("source") or {}).get("landing_page_url") or ""))
        pdf_url = str(loc.get("pdf_url") or "")
        for url in (landing, pdf_url):
            arxiv_id = _arxiv_id_from_url(url)
            if arxiv_id:
                return "arxiv", arxiv_id, []

    best = work.get("best_oa_location") or {}
    pdf = best.get("pdf_url")
    if not pdf:
        for loc in work.get("locations") or []:
            if loc.get("pdf_url"):
                pdf = loc["pdf_url"]
                break
    if not pdf:
        raise ValueError(
            f"no open-access PDF found for DOI {doi} — try pasting a direct PDF link"
        )
    return "pdf_url", str(pdf), [f"resolved DOI {doi} via OpenAlex"]


def _resolve_s2_pdf_url(
    sha: str, client: httpx.Client
) -> tuple[str, str, list[str]]:
    """Semantic Scholar: open-access PDF or arXiv upgrade for a paper SHA."""
    r = client.get(
        f"{S2_API}/{sha}",
        params={"fields": "externalIds,openAccessPdf,title"},
    )
    if r.status_code == 404:
        raise ValueError(f"paper not found on Semantic Scholar: {sha}")
    r.raise_for_status()
    paper = r.json()
    ext = paper.get("externalIds") or {}
    arxiv_id = ext.get("ArXiv")
    if arxiv_id and (
        _NEW_STYLE.fullmatch(str(arxiv_id)) or _OLD_STYLE.fullmatch(str(arxiv_id))
    ):
        return "arxiv", str(arxiv_id), []
    oa = paper.get("openAccessPdf") or {}
    url = oa.get("url")
    if url:
        return "pdf_url", str(url), []
    raise ValueError(
        f"no open-access PDF found on Semantic Scholar for {sha} — try a direct PDF link"
    )


def _pdf_url_for_kind(kind: str, ref: str, client: httpx.Client) -> tuple[str, str, list[str]]:
    """Map (kind, ref) -> (download kind, download ref, warnings)."""
    if kind == "acl":
        return "pdf_url", f"https://aclanthology.org/{ref}.pdf", []
    if kind == "openreview":
        return "pdf_url", f"https://openreview.net/pdf?id={ref}", []
    if kind == "s2":
        return _resolve_s2_pdf_url(ref, client)
    if kind == "doi":
        return _resolve_doi_pdf_url(ref, client)
    if kind == "pdf_url":
        return "pdf_url", ref, []
    raise ValueError(f"unsupported source kind: {kind}")


def fetch_source(
    kind: str,
    ref: str,
    dest_dir: Path,
    client: httpx.Client | None = None,
) -> SourceBundle:
    dest_dir.mkdir(parents=True, exist_ok=True)
    own = client is None
    c = client if client is not None else httpx.Client(timeout=120, follow_redirects=True)
    try:
        if kind == "upload":
            src = Path(ref)
            if not src.is_file():
                raise ValueError(f"uploaded file missing: {src}")
            path = dest_dir / f"{_safe_name(src.stem)}.pdf"
            path.write_bytes(src.read_bytes())
            return SourceBundle(kind="pdf", path=path, warnings=[])
        if kind == "arxiv":
            return _fetch_arxiv(ref, dest_dir, c)
        dl_kind, dl_ref, warnings = _pdf_url_for_kind(kind, ref, c)
        if dl_kind == "arxiv":  # upgraded: DOI/S2 pointed at arXiv
            bundle = _fetch_arxiv(dl_ref, dest_dir, c)
            bundle.warnings = [
                f"{kind} input resolved to arXiv {dl_ref}; using LaTeX source"
            ] + bundle.warnings
            return bundle
        return _download_pdf(dl_ref, dest_dir, dl_ref.rsplit("/", 1)[-1] or "paper", c, warnings)
    finally:
        if own:
            c.close()


def _fetch_arxiv(arxiv_id: str, dest_dir: Path, c: httpx.Client) -> SourceBundle:
    try:
        r = c.get(f"{EPRINT_URL}/{arxiv_id}")
        r.raise_for_status()
    except httpx.HTTPStatusError:
        r = None
    if r is not None:
        ctype = r.headers.get("content-type", "").lower()
        if "pdf" not in ctype:
            path = dest_dir / f"{_safe_name(arxiv_id)}.tar.gz"
            path.write_bytes(r.content)
            try:
                with tarfile.open(path) as tf:
                    tf.getmembers()
                return SourceBundle(kind="latex", path=path, warnings=[])
            except (tarfile.TarError, EOFError):
                # tar failed: maybe a bare (possibly gzipped) single .tex
                raw = r.content
                if raw[:2] == b"\x1f\x8b":
                    try:
                        import gzip

                        raw = gzip.decompress(raw)
                    except OSError:
                        raw = r.content
                if b"\\documentclass" in raw:
                    path.unlink(missing_ok=True)
                    tex_path = dest_dir / f"{_safe_name(arxiv_id)}.tex"
                    tex_path.write_bytes(raw)
                    return SourceBundle(
                        kind="latex",
                        path=tex_path,
                        warnings=["source was a single .tex file (not a tarball)"],
                    )
                path.unlink(missing_ok=True)
        else:
            # e-print served a PDF directly
            pdf_path = dest_dir / f"{_safe_name(arxiv_id)}.pdf"
            pdf_path.write_bytes(r.content)
            return SourceBundle(
                kind="pdf", path=pdf_path, warnings=[PDF_FALLBACK_WARNING]
            )
    pdf_path = dest_dir / f"{_safe_name(arxiv_id)}.pdf"
    r2 = c.get(f"{PDF_URL}/{arxiv_id}")
    r2.raise_for_status()
    pdf_path.write_bytes(r2.content)
    return SourceBundle(kind="pdf", path=pdf_path, warnings=[PDF_FALLBACK_WARNING])
