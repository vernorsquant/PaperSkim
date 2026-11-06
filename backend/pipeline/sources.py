"""Classify any paper input (ID, DOI, URL, filename-ish string) into a source kind + ref.

Pure string classification — no network. Network resolution (DOI -> OA PDF,
S2 page -> PDF) happens in the fetch stage so this stays trivially testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.pipeline.fetch import normalize_arxiv_id

KINDS = ("arxiv", "pdf_url", "doi", "s2", "openreview", "acl", "upload")


@dataclass
class SourceRef:
    kind: str
    ref: str


# ACL Anthology: aclanthology.org/2024.acl-long.123[/] — ids are like
# 2024.acl-long.123, D19-1001, W17-1234, 2020.coling-main.456
_ACL_URL = re.compile(
    r"(?:https?://)?(?:www\.)?aclanthology\.org/([A-Za-z0-9][A-Za-z0-9.\-]*?)(?:\.pdf)?"
    r"(?:[#?].*)?/?$",
    re.IGNORECASE,
)

# OpenReview forum / pdf links: ...?id=XXXX (id may be empty per pattern; require 1+)
_OPENREVIEW_URL = re.compile(
    r"(?:https?://)?(?:www\.)?openreview\.net/(?:forum|pdf)\?id=([A-Za-z0-9_\-]+)",
    re.IGNORECASE,
)

# Semantic Scholar paper page: /paper/<slug>/<40-hex> or /paper/<40-hex>
_S2_URL = re.compile(
    r"(?:https?://)?(?:www\.)?semanticscholar\.org/paper/(?:[^/?#]+/)?([0-9a-fA-F]{40})"
    r"(?:[?#].*)?$",
    re.IGNORECASE,
)

# bioRxiv / medRxiv article pages embed the DOI in the path
_BIORXIV_URL = re.compile(
    r"(?:https?://)?(?:www\.)?(?:biorxiv|medrxiv)\.org/content/(10\.[^\s?#]+?)"
    r"(?:\.?v\d+)?(?:\.full)?(?:\.pdf)?(?:[?#].*)?$",
    re.IGNORECASE,
)

# DOI resolver URLs
_DOI_URL = re.compile(
    r"(?:https?://)?(?:dx\.)?doi\.org/(10\.[^\s/?#][^\s?#]*?)(?:[?#].*)?/?$",
    re.IGNORECASE,
)

# Bare DOI: 10.<digits>/<anything without whitespace>
_DOI_BARE = re.compile(r"^(10\.\d{4,9}/\S+?)[.,;:]?$")

# arXiv-flavoured DOI: 10.48550/arXiv.2401.12345 -> upgrade to the LaTeX path
_DOI_ARXIV = re.compile(r"^10\.48550/arXiv\.(\S+)$", re.IGNORECASE)

_PLAIN_URL = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


def _clean_doi(doi: str) -> str:
    return doi.strip().rstrip("/")


def resolve_source(s: str) -> SourceRef:
    s = (s or "").strip()
    if not s:
        raise ValueError("empty input — paste a paper link, arXiv ID, or DOI")

    # arXiv first: URL, arxiv: prefix, bare new/old-style ID
    try:
        return SourceRef(kind="arxiv", ref=normalize_arxiv_id(s))
    except ValueError:
        pass

    m = _BIORXIV_URL.search(s)
    if m:
        return _doi_ref(m.group(1))

    m = _ACL_URL.match(s)
    if m:
        return SourceRef(kind="acl", ref=m.group(1))

    m = _OPENREVIEW_URL.match(s)
    if m:
        return SourceRef(kind="openreview", ref=m.group(1))

    m = _S2_URL.match(s)
    if m:
        return SourceRef(kind="s2", ref=m.group(1).lower())

    m = _DOI_URL.match(s)
    if m:
        return _doi_ref(m.group(1))

    m = _DOI_BARE.match(s)
    if m:
        return _doi_ref(m.group(1))

    if _PLAIN_URL.match(s):
        return SourceRef(kind="pdf_url", ref=s)

    raise ValueError(
        f"could not recognize input as an arXiv ID, DOI, Semantic Scholar/OpenReview/"
        f"ACL/bioRxiv URL, or direct PDF link: {s!r}"
    )


def _doi_ref(doi: str) -> SourceRef:
    doi = _clean_doi(doi)
    m = _DOI_ARXIV.match(doi)
    if m:  # arXiv-registered DOI -> use the LaTeX pipeline
        return SourceRef(kind="arxiv", ref=m.group(1))
    return SourceRef(kind="doi", ref=doi)
