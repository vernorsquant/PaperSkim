"""arXiv input normalization + source download (LaTeX preferred, PDF fallback)."""

from __future__ import annotations

import re
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx

EPRINT_URL = "https://export.arxiv.org/e-print"
PDF_URL = "https://export.arxiv.org/pdf"

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


def _safe_name(arxiv_id: str) -> str:
    return arxiv_id.replace("/", "_")


def fetch_source(
    arxiv_id: str, dest_dir: Path, client: httpx.Client | None = None
) -> SourceBundle:
    dest_dir.mkdir(parents=True, exist_ok=True)
    own = client is None
    c = client if client is not None else httpx.Client(timeout=120, follow_redirects=True)
    try:
        r = c.get(f"{EPRINT_URL}/{arxiv_id}")
        r.raise_for_status()
        ctype = r.headers.get("content-type", "").lower()
        if "pdf" not in ctype:
            path = dest_dir / f"{_safe_name(arxiv_id)}.tar.gz"
            path.write_bytes(r.content)
            try:
                with tarfile.open(path) as tf:
                    tf.getmembers()
                return SourceBundle(kind="latex", path=path, warnings=[])
            except (tarfile.TarError, EOFError):
                path.unlink(missing_ok=True)
        pdf_path = dest_dir / f"{_safe_name(arxiv_id)}.pdf"
        r2 = c.get(f"{PDF_URL}/{arxiv_id}")
        r2.raise_for_status()
        pdf_path.write_bytes(r2.content)
        return SourceBundle(kind="pdf", path=pdf_path, warnings=[PDF_FALLBACK_WARNING])
    finally:
        if own:
            c.close()
