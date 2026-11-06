"""Reviewer agent: rubric-based verdict on the draft vs the original."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

_SYSTEM = """You are a meticulous reviewer. Compare the CONDENSED DRAFT against the
ORIGINAL PAPER text and return a verdict. Check:
1. Faithfulness: no invented claims, numbers, citations, or results.
2. Coverage: the paper's main contributions are represented.
3. Jargon: rare technical terms are glossed for an undergraduate reader.
4. Figure captions: they match what the figures show per the provided descriptions.
Return ONLY JSON: {"passed": true|false, "critique": ["specific fix", ...]}
If passed is false, critique must list concrete, actionable problems."""

_GENERIC_CRITIQUE = "reviewer output was unparsable; revise the draft for faithfulness and coverage"


@dataclass
class ReviewVerdict:
    passed: bool
    critique: list[str] = field(default_factory=list)


def _parse(raw: str) -> ReviewVerdict | None:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(text[start : end + 1])
        return ReviewVerdict(
            passed=bool(data.get("passed", False)),
            critique=[str(c) for c in data.get("critique", [])],
        )
    except (ValueError, TypeError):
        return None


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


def _truncated(text: str) -> str:
    from backend.pipeline.writer import PROMPT_BUDGET_CHARS, truncate

    return truncate(text, PROMPT_BUDGET_CHARS)
