import httpx
import respx

from backend.pipeline import pareto
from backend.pipeline.pareto import (
    ModelInfo,
    fetch_models,
    rank_models,
    vision_capable,
)

MODELS_URL = "https://openrouter.ai/api/v1/models"


def _api_model(id="vendor/x", image=False, prompt="0.000002"):
    mods = ["text"] + (["image"] if image else [])
    return {
        "id": id,
        "name": id.title(),
        "pricing": {"prompt": prompt, "completion": "0.000006"},
        "architecture": {"input_modalities": mods},
    }


def test_vision_filter():
    m = ModelInfo(id="a", name="A", pricing={}, vision=True)
    assert vision_capable(m)
    assert not vision_capable(ModelInfo(id="b", name="B", pricing={}, vision=False))


@respx.mock
def test_fetch_parses_and_caches(monkeypatch):
    monkeypatch.setattr(pareto, "_CACHE", None)
    route = respx.get(MODELS_URL).respond(
        200, json={"data": [_api_model(), _api_model(id="v/eyes", image=True)]}
    )
    with httpx.Client() as c:
        models1 = fetch_models("k", client=c)
        models2 = fetch_models("k", client=c)
    assert route.call_count == 1
    assert len(models1) == 2
    assert models2 == models1
    eyes = [m for m in models1 if m.id == "v/eyes"][0]
    assert eyes.vision is True


def test_rank_prefers_frontier(monkeypatch):
    monkeypatch.setattr(
        pareto,
        "TIER_MAP",
        {"test/t3": 3, "test/t2": 2},
    )
    models = [
        ModelInfo(id="test/t3-pricey", name="P", pricing={"prompt": "0.000002"}, vision=False),
        ModelInfo(id="test/t3", name="C", pricing={"prompt": "0.000001"}, vision=False),
        ModelInfo(id="test/t2", name="M", pricing={"prompt": "0.0000005"}, vision=False),
    ]
    ranked = rank_models(models)
    ids = [r.id for r in ranked]
    # sorted strongest-tier-first, most-advanced-first WITHIN tier (user
    # mandate 2026-11-08: the pricier flagship variant leads its tier);
    # tier-2 follows after tier-3
    assert ids == ["test/t3-pricey", "test/t3", "test/t2"]
    assert ranked[0].tier == 3
    assert ranked[0].prompt_cost == 0.000002


def test_rank_ignores_free_and_negative_costs(monkeypatch):
    monkeypatch.setattr(pareto, "TIER_MAP", {"test/t3": 3})
    models = [
        ModelInfo(id="test/t3:free", name="F", pricing={"prompt": "0"}, vision=True),
        ModelInfo(id="test/t3:batch", name="B", pricing={"prompt": "-1"}, vision=False),
        ModelInfo(id="other/junk", name="J", pricing={"prompt": "-1"}, vision=False),
        ModelInfo(id="test/t3", name="C", pricing={"prompt": "0.000001"}, vision=True),
    ]
    ranked = rank_models(models)
    ids = [r.id for r in ranked]
    assert "test/t3:free" not in ids
    assert "other/junk" not in ids
    assert ids[0] == "test/t3"


def test_rank_dedupes_variants_keeps_base(monkeypatch):
    monkeypatch.setattr(pareto, "TIER_MAP", {"test/t3": 3})
    models = [
        ModelInfo(id="test/t3", name="C", pricing={"prompt": "0.000002"}, vision=True),
        ModelInfo(id="test/t3:thinking", name="CT", pricing={"prompt": "0.000001"}, vision=True),
    ]
    ranked = rank_models(models)
    assert [r.id for r in ranked] == ["test/t3"]
