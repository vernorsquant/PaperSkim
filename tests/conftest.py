import io
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

MAIN_TEX = b"""
\\documentclass{article}
\\title{Echo-State Networks for Inference}
\\begin{document}
\\maketitle
\\section{Introduction}
We study recurrent dynamics.
\\input{sections/intro}
\\begin{figure}[h]
\\centering
\\includegraphics[width=0.8\\textwidth]{fig1.png}
\\caption{Reservoir computing accuracy versus spectral radius.}
\\label{fig:acc}
\\end{figure}
100\\% sure this stays. % this hidden note vanishes
\\end{document}
"""

INTRO_TEX = b"""
\\section{Results}
The reservoir memory capacity peaks at radius one.
\\input{sections/deep/notes}
"""

NOTES_TEX = b"""
\\section{Details}
Deep nested notes body appears here.
"""

MINI_SOURCE = {
    "main.tex": MAIN_TEX,
    "sections/intro.tex": INTRO_TEX,
    "sections/deep/notes.tex": NOTES_TEX,
    "fig1.png": b"\x89PNG fake image bytes",
}

CYCLE_SOURCE = {
    "a.tex": b"\\documentclass{article}\\begin{document}\\input{b}\\end{document}",
    "b.tex": b"\\input{a}",
}

MINIMAL_TEX = "\\documentclass{article}\\begin{document}Hello PDF world.\\end{document}\n"


def make_tar_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture(scope="session")
def mini_tar(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("mini") / "mini.tar.gz"
    p.write_bytes(make_tar_bytes(MINI_SOURCE))
    return p


@pytest.fixture(scope="session")
def cycle_tar(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("cycle") / "cycle.tar.gz"
    p.write_bytes(make_tar_bytes(CYCLE_SOURCE))
    return p


@pytest.fixture(scope="session")
def simple_pdf(tmp_path_factory) -> Path:
    """A real 1-page PDF compiled with tectonic; skipped if tectonic is absent."""
    if shutil.which("tectonic") is None:
        pytest.skip("tectonic not installed")
    d = tmp_path_factory.mktemp("pdf")
    tex = d / "minimal.tex"
    tex.write_text(MINIMAL_TEX)
    subprocess.run(
        ["tectonic", "-X", "compile", str(tex), "--outdir", str(d)],
        check=True,
        capture_output=True,
        timeout=180,
    )
    return d / "minimal.pdf"
