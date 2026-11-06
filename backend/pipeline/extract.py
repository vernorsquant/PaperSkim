"""Extract text, sections, and figures from an arXiv source bundle."""

from __future__ import annotations

import re
import shutil
import subprocess
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

from backend.pipeline.fetch import SourceBundle

_IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".pdf", ".eps"]

_INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
_TITLE_RE = re.compile(r"\\title\s*")
_SECTION_RE = re.compile(r"\\section\*?\s*")
_FIGURE_ENV_RE = re.compile(
    r"\\begin\{figure\*?\}.*?\\end\{figure\*?\}", re.DOTALL
)
_INCLUDEGRAPHICS_RE = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}"
)
_CAPTION_RE = re.compile(r"\\caption\s*")
_COMMENT_RE = re.compile(r"(?<!\\)%.*")
_MAX_INPUT_DEPTH = 16


def _group_span(text: str, match: re.Match) -> tuple[str, int] | None:
    """Return (content, end_index) of the brace-balanced group after a command match."""
    brace = text.find("{", match.end() - 1)
    if brace == -1:
        return None
    depth = 0
    i = brace
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[brace + 1 : i], i + 1
        i += 1
    return None


def _group_after(text: str, match: re.Match) -> str | None:
    span = _group_span(text, match)
    return span[0] if span else None


@dataclass
class Figure:
    path: Path
    caption: str | None


@dataclass
class Paper:
    arxiv_id: str
    title: str
    full_text: str
    sections: list[tuple[str, str]]
    figures: list[Figure]
    warnings: list[str] = field(default_factory=list)


def _strip_comments(text: str) -> str:
    return "\n".join(_COMMENT_RE.sub("", line) for line in text.splitlines())


def _find_main_tex(root: Path) -> Path:
    candidates = [
        p for p in root.rglob("*.tex") if "\\documentclass" in p.read_text(errors="ignore")
    ]
    if not candidates:
        raise ValueError("no main .tex (with \\documentclass) found in source")
    return min(candidates, key=lambda p: (len(p.parts), p.name != "main.tex"))


def _inside_root(root: Path, cand: Path) -> bool:
    try:
        cand.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_input(root: Path, target: str, visited: set[Path]) -> Path | None:
    name = target.strip()
    if name.startswith("/") or ".." in Path(name).parts:
        return None
    for cand in (
        root / name,
        root / f"{name}.tex",
    ):
        cand = cand.resolve()
        if cand.is_file() and cand not in visited and _inside_root(root.resolve(), cand):
            return cand
    return None


def _flatten(text: str, root: Path, visited: set[Path], depth: int = 0) -> str:
    if depth > _MAX_INPUT_DEPTH:
        return text

    def repl(m: re.Match) -> str:
        resolved = _resolve_input(root, m.group(1), visited)
        if resolved is None:
            return ""
        visited.add(resolved)
        inner = resolved.read_text(errors="ignore")
        return _flatten(inner, root, visited, depth + 1)

    return _INPUT_RE.sub(repl, text)


def _resolve_figure(root: Path, graphics: str) -> Path | None:
    name = graphics.strip()
    if not name or Path(name).is_absolute():
        return None
    p = (root / name).resolve()
    if not _inside_root(root.resolve(), p):
        return None
    if p.is_file():
        return p
    for ext in _IMAGE_EXTS:
        cand = p.with_suffix(ext)
        if cand.is_file():
            return cand
    return None


def _extract_figures(root: Path, text: str) -> list[Figure]:
    figures: list[Figure] = []
    seen: set[Path] = set()

    def add(path: Path | None, caption: str | None) -> None:
        if path is None or path in seen:
            return
        seen.add(path)
        figures.append(Figure(path=path, caption=caption))

    for env_m in _FIGURE_ENV_RE.finditer(text):
        env = env_m.group(0)
        cap_m = _CAPTION_RE.search(env)
        caption = _group_after(env, cap_m) if cap_m else None
        if caption:
            caption = _strip_comments(caption).strip()
        for g_m in _INCLUDEGRAPHICS_RE.finditer(env):
            add(_resolve_figure(root, g_m.group(1)), caption)

    # includegraphics outside figure environments: no captions
    body_wo_envs = _FIGURE_ENV_RE.sub("", text)
    for g_m in _INCLUDEGRAPHICS_RE.finditer(body_wo_envs):
        add(_resolve_figure(root, g_m.group(1)), None)
    return figures


def _extract_sections(text: str) -> list[tuple[str, str]]:
    matches = list(_SECTION_RE.finditer(text))
    sections: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        span = _group_span(text, m)
        body_start = span[1] if span else m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        name = span[0] if span else "?"
        sections.append((name.strip(), text[body_start:end].strip()))
    return sections


def _extract_latex(bundle: SourceBundle, arxiv_id: str, workdir: Path) -> Paper:
    root = workdir / "source"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    tar_ok = tarfile.is_tarfile(bundle.path)
    if tar_ok:
        with tarfile.open(bundle.path) as tar:
            tar.extractall(root, filter="data")
        main = _find_main_tex(root)
    else:
        # single-file source (bare .tex from arXiv)
        main = root / "main.tex"
        shutil.copy2(bundle.path, main)
    visited = {main.resolve()}
    text = _flatten(main.read_text(errors="ignore"), root, visited)
    text = _strip_comments(text)
    title_m = _TITLE_RE.search(text)
    title = _group_after(text, title_m) if title_m else None
    return Paper(
        arxiv_id=arxiv_id,
        title=title.strip() if title else arxiv_id,
        full_text=text,
        sections=_extract_sections(text),
        figures=_extract_figures(root, text),
        warnings=list(bundle.warnings),
    )


def _extract_pdf(bundle: SourceBundle, arxiv_id: str, workdir: Path) -> Paper:
    workdir.mkdir(parents=True, exist_ok=True)
    txt_path = workdir / "paper.txt"
    subprocess.run(
        ["pdftotext", str(bundle.path), str(txt_path)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    text = txt_path.read_text(errors="ignore")
    return Paper(
        arxiv_id=arxiv_id,
        title=arxiv_id,
        full_text=text,
        sections=[],
        figures=[],
        warnings=list(bundle.warnings),
    )


def extract_paper(bundle: SourceBundle, arxiv_id: str, workdir: Path) -> Paper:
    if bundle.kind == "latex":
        return _extract_latex(bundle, arxiv_id, workdir)
    return _extract_pdf(bundle, arxiv_id, workdir)
