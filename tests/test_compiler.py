import shutil

import pytest

from backend.pipeline.compiler import compile_tex

pytestmark = pytest.mark.skipif(
    shutil.which("tectonic") is None, reason="tectonic not installed"
)


def _tex(path, body):
    path.write_text(body)
    return path


OK_TEX = "\\documentclass{article}\n\\begin{document}It works.\n\\end{document}\n"
BROKEN_TEX = "\\documentclass{article}\n\\usepackage{notarealpackage123}\n\\begin{document}x\n\\end{document}\n"


def test_compile_ok(tmp_path):
    tex = _tex(tmp_path / "ok.tex", OK_TEX)
    res = compile_tex(tex, tmp_path / "out")
    assert res.ok
    assert res.pdf_path is not None and res.pdf_path.exists()
    assert res.pages == 1
    assert res.log


def test_repair_called_once(tmp_path):
    tex = _tex(tmp_path / "broken.tex", BROKEN_TEX)
    calls = []

    def repair_fn(log):
        calls.append(log)
        fixed = tmp_path / f"fixed{len(calls)}.tex"
        fixed.write_text(OK_TEX)
        return str(fixed)

    res = compile_tex(tex, tmp_path / "out2", repair_fn=repair_fn)
    assert res.ok
    assert len(calls) == 1
    assert res.pages == 1


def test_repair_exhausted(tmp_path):
    tex = _tex(tmp_path / "broken.tex", BROKEN_TEX)
    calls = []

    def repair_fn(log):
        calls.append(log)
        still_broken = tmp_path / f"still{len(calls)}.tex"
        still_broken.write_text(BROKEN_TEX)
        return str(still_broken)

    res = compile_tex(tex, tmp_path / "out3", repair_fn=repair_fn)
    assert not res.ok
    assert res.pdf_path is None
    assert len(calls) == 1  # exactly one repair pass, no loop
    assert "notarealpackage123" in res.log or res.log
