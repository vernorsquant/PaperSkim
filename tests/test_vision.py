import json
from pathlib import Path

from backend.pipeline.vision import Caption, describe_figures, select_figures


def _figs(n, captioned=0, tmp=None):
    tmp = tmp or Path("/tmp/figs")
    out = []
    for i in range(n):
        cap = f"caption {i}" if i < captioned else None
        out.append(type("F", (), {"path": tmp / f"f{i}.png", "caption": cap})())
    return out


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def vision(self, model, prompt, images):
        self.calls.append(len(images))
        return self.responses.pop(0)


def test_select_prefers_captions_and_caps():
    figs = _figs(14, captioned=3)
    sel = select_figures(figs, cap=12)
    assert len(sel) == 12
    assert all(f.caption is not None for f in sel[:3])
    assert sel[3].caption is None


def test_batches_of_five():
    c = FakeClient(["[]"] * 3)
    figs = _figs(11)
    describe_figures(c, "vm", figs)
    assert c.calls == [5, 5, 1]


def test_parses_captions(tmp_path):
    figs = _figs(2, tmp=tmp_path)
    payload = json.dumps(
        [
            {"index": 0, "summary": "s0", "axes": "a0", "takeaway": "t0", "jargon": ["x"]},
            {"index": 1, "summary": "s1", "axes": "a1", "takeaway": "t1", "jargon": []},
        ]
    )
    c = FakeClient([payload])
    caps = describe_figures(c, "vm", figs)
    assert len(caps) == 2
    c0 = caps[str(figs[0].path)]
    assert isinstance(c0, Caption)
    assert c0.summary == "s0"
    assert c0.to_dict()["jargon"] == ["x"]


def test_bad_json_skips_batch(tmp_path):
    figs = _figs(6, tmp=tmp_path)
    good = json.dumps(
        [{"index": 0, "summary": "ok", "axes": "", "takeaway": "", "jargon": []}]
    )
    c = FakeClient(["not json at all", good])
    warnings: list[str] = []
    caps = describe_figures(c, "vm", figs, warnings=warnings)
    assert str(figs[5].path) in caps  # good batch is batch 1 -> f5
    assert len(caps) == 1
    assert warnings and "batch 0" in warnings[0]


def test_llm_error_skips_batch(tmp_path):
    figs = _figs(7, tmp=tmp_path)  # batches of 5+2 -> two batches
    payload = json.dumps(
        [{"index": 0, "summary": "s", "axes": "", "takeaway": "", "jargon": []}]
    )
    c = FakeClient([payload])

    class Boom:
        def vision(self, model, prompt, images):
            from backend.pipeline.llm import LLMError

            raise LLMError("502 upstream")

    # first batch errors at the HTTP layer, second succeeds
    flaky = FlakyVision([Boom(), c])
    warnings: list[str] = []
    caps = describe_figures(flaky, "vm", figs, warnings=warnings)
    assert len(caps) == 1
    assert warnings and "batch 0" in warnings[0]


class FlakyVision:
    def __init__(self, clients):
        self.clients = list(clients)

    def vision(self, model, prompt, images):
        client = self.clients.pop(0)
        return client.vision(model, prompt, images)
