"""tectonic compile wrapper with a single error-log repair pass."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

COMPILE_TIMEOUT_S = 300


@dataclass
class CompileResult:
    ok: bool
    pdf_path: Path | None
    log: str
    pages: int


def page_count(pdf_path: Path) -> int:
    out = subprocess.run(
        ["pdfinfo", str(pdf_path)], capture_output=True, text=True, timeout=30
    )
    for line in out.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    return 0


def _run_tectonic(tex_path: Path, outdir: Path) -> tuple[bool, str, Path | None]:
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            [
                "tectonic",
                "-X",
                "compile",
                str(tex_path),
                "--outdir",
                str(outdir),
                "--keep-logs",
                "--keep-intermediates",
            ],
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False, f"tectonic timed out after {COMPILE_TIMEOUT_S}s", None
    log = (proc.stdout or "") + (proc.stderr or "")
    pdf = outdir / f"{tex_path.stem}.pdf"
    if proc.returncode == 0 and pdf.exists():
        return True, log, pdf
    return False, log or f"tectonic exited {proc.returncode}", None


def compile_tex(
    tex_path: Path,
    outdir: Path,
    allow_repair: bool = True,
    repair_fn=None,
) -> CompileResult:
    ok, log, pdf = _run_tectonic(tex_path, outdir)
    if not ok and allow_repair and repair_fn is not None:
        new_tex = Path(repair_fn(log))
        ok, log2, pdf2 = _run_tectonic(new_tex, outdir)
        log = f"{log}\n--- repair pass ({new_tex.name}) ---\n{log2}"
        pdf = pdf2
    pages = page_count(pdf) if ok and pdf is not None else 0
    return CompileResult(ok=ok, pdf_path=pdf, log=log, pages=pages)
