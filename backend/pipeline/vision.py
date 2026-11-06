"""Vision stage: figure selection + batched vision-model captioning."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from backend.pipeline.extract import Figure
from backend.pipeline.llm import LLMError

BATCH_SIZE = 5
FIGURE_CAP = 12

_PROMPT_TEMPLATE = """You are given {n} figure images from a scientific paper, indexed 0..{last}.
For EACH image, describe it so a writer can reference it in text without seeing it.
Return ONLY a JSON array (no markdown fences), one object per image:
[{{"index": 0, "summary": "...", "axes": "...", "takeaway": "...", "jargon": ["term", ...]}}]
- summary: what the figure shows overall
- axes: axis/panel structure (say "none" for diagrams)
- takeaway: the single key result the figure communicates
- jargon: technical terms appearing in the figure or needed to understand it"""


@dataclass
class Caption:
    summary: str
    axes: str
    takeaway: str
    jargon: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "axes": self.axes,
            "takeaway": self.takeaway,
            "jargon": self.jargon,
        }


def select_figures(figures: list[Figure], cap: int = FIGURE_CAP) -> list[Figure]:
    captioned = [f for f in figures if f.caption]
    uncaptioned = [f for f in figures if not f.caption]
    return (captioned + uncaptioned)[:cap]


def _parse_batch(raw: str, batch: list[Figure]) -> dict[str, Caption]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    data = json.loads(text)
    out: dict[str, Caption] = {}
    for item in data:
        idx = int(item["index"])
        if 0 <= idx < len(batch):
            out[str(batch[idx].path)] = Caption(
                summary=str(item.get("summary", "")),
                axes=str(item.get("axes", "")),
                takeaway=str(item.get("takeaway", "")),
                jargon=[str(j) for j in item.get("jargon", [])],
            )
    return out


def describe_figures(
    client,
    model: str,
    figures: list[Figure],
    batch_size: int = BATCH_SIZE,
    warnings: list[str] | None = None,
) -> dict[str, Caption]:
    captions: dict[str, Caption] = {}
    if warnings is None:
        warnings = []
    for i in range(0, len(figures), batch_size):
        batch = figures[i : i + batch_size]
        prompt = _PROMPT_TEMPLATE.format(n=len(batch), last=len(batch) - 1)
        try:
            raw = client.vision(model, prompt, [f.path for f in batch])
            captions.update(_parse_batch(raw, batch))
        except (ValueError, KeyError, TypeError, OSError, LLMError) as e:
            warnings.append(f"vision batch {i // batch_size} failed ({e}); figures omitted")
    return captions
