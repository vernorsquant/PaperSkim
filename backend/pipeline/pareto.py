"""OpenRouter model listing + capability/cost Pareto-frontier ranking."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL_S = 3600

# Curated capability tiers (4 = frontier flagship, 3 = strong generalist).
# Longest matching id prefix wins; unknown models get tier 1.
TIER_MAP: dict[str, int] = {
    "openai/gpt-5": 4,
    "anthropic/claude-opus": 4,
    "anthropic/claude-sonnet": 4,
    "google/gemini-2.5-pro": 4,
    "google/gemini-3-pro": 4,
    "x-ai/grok-4": 4,
    "deepseek/deepseek-v3": 3,
    "deepseek/deepseek-chat": 3,
    "google/gemini-2.5-flash": 3,
    "google/gemini-3-flash": 3,
    "openai/gpt-4o": 3,
    "qwen/qwen3-max": 3,
    "moonshotai/kimi-k2": 3,
    "z-ai/glm-4": 3,
    "z-ai/glm-5": 3,
    # more-specific prefixes override the flagship rules above (longest
    # prefix wins): the small gpt-5 variants are NOT frontier flagships.
    "openai/gpt-5-mini": 3,
    "openai/gpt-5-nano": 2,
    "anthropic/claude-haiku": 2,
    "openai/gpt-4o-mini": 2,
    "google/gemini-2.0-flash": 2,
    "meta-llama/llama-4": 2,
    "mistralai/mistral-large": 2,
}

_CACHE: dict | None = None  # {"fetched_at": float, "data": list[ModelInfo]}


@dataclass
class ModelInfo:
    id: str
    name: str
    pricing: dict
    vision: bool
    context_length: int = 0


@dataclass
class RankedModel:
    id: str
    name: str
    vision: bool
    tier: int
    prompt_cost: float
    context_length: int = 0


def vision_capable(m: ModelInfo) -> bool:
    return m.vision


def _tier_for(model_id: str, tier_map: dict[str, int]) -> int:
    best_prefix, best_tier = "", 0
    for prefix, tier in tier_map.items():
        if model_id.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix, best_tier = prefix, tier
    return best_tier if best_prefix else 1


def fetch_models(api_key: str, client: httpx.Client | None = None) -> list[ModelInfo]:
    global _CACHE
    if _CACHE is not None and time.time() - _CACHE["fetched_at"] < CACHE_TTL_S:
        return _CACHE["data"]
    own = client is None
    c = client if client is not None else httpx.Client(timeout=30)
    try:
        r = c.get(
            MODELS_URL, headers={"Authorization": f"Bearer {api_key}"}
        )
        r.raise_for_status()
        raw = r.json().get("data", [])
        models = [
            ModelInfo(
                id=m["id"],
                name=m.get("name", m["id"]),
                pricing=m.get("pricing", {}) or {},
                vision="image"
                in ((m.get("architecture") or {}).get("input_modalities") or []),
                context_length=int(m.get("context_length") or 0),
            )
            for m in raw
        ]
        _CACHE = {"fetched_at": time.time(), "data": models}
        return models
    finally:
        if own:
            c.close()


def _prompt_cost(m: ModelInfo) -> float:
    try:
        return float(m.pricing.get("prompt", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def rank_models(
    models: list[ModelInfo], tier_map: dict[str, int] | None = None
) -> list[RankedModel]:
    tm = tier_map if tier_map is not None else TIER_MAP
    ranked = [
        RankedModel(
            id=m.id,
            name=m.name,
            vision=m.vision,
            tier=_tier_for(m.id, tm),
            prompt_cost=_prompt_cost(m),
            context_length=m.context_length,
        )
        for m in models
    ]
    # drop free/batch/variable-priced variants: cost<=0 is pricing noise that
    # would otherwise dominate the frontier
    ranked = [r for r in ranked if r.prompt_cost > 0]
    # collapse variants (id:free, id:batch, id:thinking...) onto the base id:
    # keep the cheapest variant per family, prefer the exact base id
    families: dict[str, RankedModel] = {}
    for r in ranked:
        family = r.id.split(":", 1)[0]
        cur = families.get(family)
        if (
            cur is None
            or r.id == family
            or (cur.id != family and r.prompt_cost < cur.prompt_cost)
        ):
            families[family] = RankedModel(
                id=family,
                name=r.name,
                vision=r.vision,
                tier=r.tier,
                prompt_cost=r.prompt_cost,
                context_length=r.context_length,
            )
    frontier = list(families.values())
    # most-advanced-first (user mandate 2026-11-08): tier desc, then the
    # pricier flagship variant first WITHIN a tier — price tracks capability
    # closely enough inside a tier, and the user wants the dropdown ordered
    # strongest-at-top, not cheapest-at-top.
    frontier.sort(key=lambda r: (-r.tier, -r.prompt_cost, r.id))
    return frontier
