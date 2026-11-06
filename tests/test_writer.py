import json

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


def test_review_unparsable_is_fail():
    c = FakeChat(["I think it looks fine!"])
    v = review(c, "rm", make_paper(), "DRAFT")
    assert v.passed is False
    assert v.critique
