"""Writer agent: condensed LaTeX drafting + review/revise loop."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from backend.pipeline.extract import Paper
from backend.pipeline.reviewer import review

PROMPT_BUDGET_CHARS = 90000
PAGE_TOLERANCE = 1

_DRAFT_SYSTEM = """You are an expert science writer. Rewrite the paper as a CONDENSED,
self-contained LaTeX article that a smart undergraduate can understand.
Rules:
- Keep the paper's actual story and results; NEVER invent claims, numbers, or citations.
- Explain rare jargon at first use (short parenthetical gloss); everyday language elsewhere.
- Use ONLY a complete, compilable preamble (article class, graphicx, amsmath, hyperref,
  geometry margins=1in). No custom .sty files, no bibliography environment.
- Embed figures with \\includegraphics using exactly the FIGURE PATHS given; pair each
  with a caption informed by its description.
- Length: the compiled PDF must be about {target_pages} pages.
- Output ONLY the LaTeX source, no markdown fences, no commentary."""


def truncate(text: str, budget: int = PROMPT_BUDGET_CHARS) -> str:
    return text[:budget]


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def copy_figure_assets(paper: Paper, outdir: Path) -> dict[str, str]:
    """Copy selected figure files into outdir/figures/; return {source_path: tex_path}."""
    figdir = outdir / "figures"
    figdir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for fig in paper.figures:
        name = fig.path.name
        stem, ext = Path(name).stem, Path(name).suffix or ".png"
        candidate = name
        i = 1
        while candidate in used:
            candidate = f"{stem}_{i}{ext}"
            i += 1
        used.add(candidate)
        shutil.copy2(fig.path, figdir / candidate)
        mapping[str(fig.path)] = f"figures/{candidate}"
    return mapping


def build_draft_messages(
    paper: Paper,
    captions: dict,
    target_pages: int,
    fig_map: dict[str, str] | None = None,
    adjust: str | None = None,
) -> list[dict]:
    fm = fig_map or {str(f.path): f"figures/{f.path.name}" for f in paper.figures}
    cap_json = json.dumps(
        {p: c.to_dict() if hasattr(c, "to_dict") else c for p, c in captions.items()},
        indent=1,
    )
    figure_lines = "\n".join(
        f"- \\path{{{tex}}} (original: {orig})"
        + (
            f" description: {captions.get(orig, captions.get(tex, ''))}"
            if (orig in captions or tex in captions)
            else ""
        )
        for orig, tex in fm.items()
    )
    user = (
        f"PAPER TITLE: {paper.title}\n\n"
        f"FULL TEXT:\n{truncate(paper.full_text)}\n\n"
        f"FIGURES (embed these paths):\n{figure_lines}\n\n"
        f"FIGURE DESCRIPTIONS (JSON):\n{cap_json}\n\n"
        f"TARGET LENGTH: {target_pages} pages.\n"
    )
    if adjust:
        user += f"\nREVISION INSTRUCTION (apply fully):\n{adjust}\n"
    user += "\nReturn the complete LaTeX source now."
    return [
        {"role": "system", "content": _DRAFT_SYSTEM.format(target_pages=target_pages)},
        {"role": "user", "content": user},
    ]


def draft_once(
    client,
    model: str,
    paper: Paper,
    captions: dict,
    target_pages: int,
    fig_map: dict[str, str] | None = None,
    adjust: str | None = None,
) -> str:
    messages = build_draft_messages(paper, captions, target_pages, fig_map, adjust)
    return _strip_fences(client.chat(model, messages))


# Untrusted LLM output must not read arbitrary files into the compiled PDF.
_DANGEROUS_TEX_RE = re.compile(
    r"\\(?:input|include|openin|openoutput|read|write(?:18)?|directlua|luaexec)\b[^\n]*"
)
_INCLUDEGRAPHICS_TEX_RE = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}"
)


def _sanitize_tex(tex: str, allowed_figs: list[str]) -> str:
    tex = _DANGEROUS_TEX_RE.sub("", tex)
    allowed = {p.replace("\\", "/") for p in allowed_figs}

    def repl(m: re.Match) -> str:
        norm = m.group(1).strip().replace("\\", "/")
        return m.group(0) if norm in allowed else ""

    return _INCLUDEGRAPHICS_TEX_RE.sub(repl, tex)


@dataclass
class IterationResult:
    tex_path: Path
    pdf_path: Path | None
    pages: int
    rounds: int
    passed: bool


def _page_adjustment(pages: int, target: int) -> str | None:
    if abs(pages - target) <= PAGE_TOLERANCE:
        return None
    if pages > target:
        return (
            f"The draft compiled to {pages} pages; the target is {target}. "
            "Cut depth: fewer subsections, tighter prose. Keep all key results."
        )
    return (
        f"The draft compiled to only {pages} pages; the target is {target}. "
        "Expand: explain methods and results in more depth."
    )


def _write_tex(tex: str, fig_map: dict[str, str], tex_path: Path) -> None:
    tex_path.write_text(_sanitize_tex(tex, list(fig_map.values())))


def write_and_refine(
    client,
    writer_model: str,
    reviewer_model: str,
    paper: Paper,
    captions: dict,
    target_pages: int,
    workdir: Path,
    max_rounds: int = 3,
    compile_fn=None,
    on_stage=None,
) -> IterationResult:
    if compile_fn is None:
        from backend.pipeline.compiler import compile_tex

        compile_fn = compile_tex
    workdir.mkdir(parents=True, exist_ok=True)
    tex_path = workdir / "paper.tex"
    fig_map = copy_figure_assets(paper, workdir)

    tex = draft_once(client, writer_model, paper, captions, target_pages, fig_map)
    _write_tex(tex, fig_map, tex_path)
    res = compile_fn(tex_path, workdir)
    if on_stage:
        on_stage("draft")

    # single self-repair pass on compile failure
    if not res.ok:
        tex = draft_once(
            client,
            writer_model,
            paper,
            captions,
            target_pages,
            fig_map,
            adjust=f"Your previous LaTeX failed to compile. Error log:\n{truncate(res.log, 4000)}\n"
            "Return corrected, complete LaTeX.",
        )
        _write_tex(tex, fig_map, tex_path)
        res = compile_fn(tex_path, workdir)
    else:
        # single page-budget adjustment
        adjustment = _page_adjustment(res.pages, target_pages)
        if adjustment is not None:
            tex = draft_once(
                client, writer_model, paper, captions, target_pages, fig_map, adjustment
            )
            _write_tex(tex, fig_map, tex_path)
            res = compile_fn(tex_path, workdir)

    for round_no in range(1, max_rounds + 1):
        if on_stage:
            on_stage("review")
        verdict = review(client, reviewer_model, paper, tex)
        if verdict.passed:
            return IterationResult(
                tex_path=tex_path,
                pdf_path=res.pdf_path if res.ok else None,
                pages=res.pages if res.ok else 0,
                rounds=round_no,
                passed=True,
            )
        critique = "\n".join(f"- {c}" for c in verdict.critique)
        if on_stage and round_no < max_rounds:
            on_stage("revise")
        tex = draft_once(
            client,
            writer_model,
            paper,
            captions,
            target_pages,
            fig_map,
            adjust=f"The reviewer rejected the draft. Fix every point:\n{critique}",
        )
        _write_tex(tex, fig_map, tex_path)
        res = compile_fn(tex_path, workdir)

    return IterationResult(
        tex_path=tex_path,
        pdf_path=res.pdf_path if res.ok else None,
        pages=res.pages if res.ok else 0,
        rounds=max_rounds,
        passed=False,
    )
