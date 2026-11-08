"""Reviewer agents: rubric verdict + coverage audit + accuracy fact-check."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

_SYSTEM = """You are a meticulous reviewer. Compare the CONDENSED DRAFT against the
ORIGINAL PAPER text and return a verdict. Check:
1. Faithfulness: no invented claims, numbers, citations, or results.
2. Coverage: the paper's main contributions are represented. List every important
   element of the original (methods, results, key numbers, limitations, figures)
   that is missing or unacceptably thin in the draft under "missing".
3. Jargon: rare technical terms are glossed for an undergraduate reader.
4. Figure captions: they match what the figures show per the provided descriptions.
Set "passed" to false whenever anything important is missing.
Return ONLY JSON: {"passed": true|false, "critique": ["specific fix", ...],
"missing": ["important content absent from the draft", ...]}
If passed is false, critique must list concrete, actionable problems."""

_VERIFY_SYSTEM = """You are a meticulous fact-checker. Compare the CONDENSED DRAFT
against the ORIGINAL PAPER and audit ACCURACY only:
- every number, statistic, and equation result in the draft must match the original
- no invented or misattributed claims, citations, or results
- stated directions of effects (improves/worsens, significant/not) must match
Return ONLY JSON: {"accurate": true|false, "issues": ["specific error + correction", ...]}"""

_GENERIC_CRITIQUE = "reviewer output was unparsable; revise the draft for faithfulness and coverage"


@dataclass
class ReviewVerdict:
    passed: bool
    critique: list[str] = field(default_factory=list)
    # important content of the original that is absent/thin in the draft
    missing: list[str] = field(default_factory=list)


@dataclass
class AccuracyVerdict:
    accurate: bool
    issues: list[str] = field(default_factory=list)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _extract_json(text: str) -> dict | None:
    text = _strip_fences(text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None


def _parse(raw: str) -> ReviewVerdict | None:
    data = _extract_json(raw)
    if data is None:
        return None
    return ReviewVerdict(
        passed=bool(data.get("passed", False)),
        critique=[str(c) for c in data.get("critique", [])],
        missing=[str(m) for m in data.get("missing", [])],
    )


def review(client, model, paper, draft_tex: str) -> ReviewVerdict:
    user = (
        f"ORIGINAL PAPER (title: {paper.title}):\n"
        f"{_truncated(paper.full_text)}\n\n"
        f"CONDENSED DRAFT (LaTeX):\n{_truncated(draft_tex)}\n\n"
        "Return the verdict JSON."
    )
    raw = client.chat(model, [{"role": "system", "content": _SYSTEM},
                              {"role": "user", "content": user}])
    return _parse(raw) or ReviewVerdict(passed=False, critique=[_GENERIC_CRITIQUE])


def verify_accuracy(client, model, paper, draft_tex: str) -> AccuracyVerdict:
    """Post-review accuracy pass: numbers/claims in the draft vs the original.

    An unparsable fact-check is treated as no findings — the rubric review has
    already run, and a parser hiccup must not block delivery.
    """
    user = (
        f"ORIGINAL PAPER (title: {paper.title}):\n"
        f"{_truncated(paper.full_text)}\n\n"
        f"CONDENSED DRAFT (LaTeX):\n{_truncated(draft_tex)}\n\n"
        "Return the accuracy verdict JSON."
    )
    raw = client.chat(model, [{"role": "system", "content": _VERIFY_SYSTEM},
                              {"role": "user", "content": user}])
    data = _extract_json(raw)
    if data is None:
        return AccuracyVerdict(accurate=True, issues=[])
    return AccuracyVerdict(
        accurate=bool(data.get("accurate", True)),
        issues=[str(i) for i in data.get("issues", [])],
    )


def _truncated(text: str) -> str:
    from backend.pipeline.writer import PROMPT_BUDGET_CHARS, truncate

    return truncate(text, PROMPT_BUDGET_CHARS)
