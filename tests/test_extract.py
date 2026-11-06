from pathlib import Path

from backend.pipeline.extract import extract_paper
from backend.pipeline.fetch import SourceBundle


def _latex(bundle_path: Path, tmp_path: Path):
    return extract_paper(
        SourceBundle(kind="latex", path=bundle_path, warnings=[]),
        "2401.12345",
        tmp_path / "work",
    )


def test_title_extracted(mini_tar, tmp_path):
    paper = _latex(mini_tar, tmp_path)
    assert paper.title == "Echo-State Networks for Inference"


def test_input_flattened(mini_tar, tmp_path):
    paper = _latex(mini_tar, tmp_path)
    assert "recurrent dynamics" in paper.full_text
    assert "Deep nested notes body appears here" in paper.full_text


def test_cycle_guard(cycle_tar, tmp_path):
    paper = _latex(cycle_tar, tmp_path)  # must terminate
    assert paper.full_text


def test_comments_stripped(mini_tar, tmp_path):
    paper = _latex(mini_tar, tmp_path)
    assert "hidden note" not in paper.full_text
    assert "100\\% sure this stays" in paper.full_text


def test_figures_with_captions(mini_tar, tmp_path):
    paper = _latex(mini_tar, tmp_path)
    assert len(paper.figures) == 1
    fig = paper.figures[0]
    assert fig.path.name == "fig1.png"
    assert fig.path.exists()
    assert "spectral radius" in (fig.caption or "")


def test_sections_split(mini_tar, tmp_path):
    paper = _latex(mini_tar, tmp_path)
    names = [n for n, _ in paper.sections]
    assert "Introduction" in names
    assert "Results" in names
    assert "Details" in names


def test_pdf_fallback_text_only(simple_pdf, tmp_path):
    paper = extract_paper(
        SourceBundle(kind="pdf", path=simple_pdf, warnings=["pdf fallback"]),
        "2401.12345",
        tmp_path / "work_pdf",
    )
    assert "Hello PDF world" in paper.full_text
    assert paper.figures == []
    assert paper.warnings
