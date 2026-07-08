from __future__ import annotations
import math, re, time
from aiintel.models import Item

_WEIGHT_POINTS = {"high": 3, "med": 2, "low": 1}
_TRUST_MULT = {"vendor": 1.5, "curated": 1.2, "community": 1.0}

def _topic_hits(title_norm: str, topics: list[str]) -> bool:
    for topic in topics:
        words = topic.lower().split()
        if all(re.search(rf"\b{re.escape(w)}\b", title_norm) for w in words):
            return True
    return False

def _velocity(it: Item, now: float) -> float:
    age_h = max((now - it.published) / 3600, 2.0)
    if it.source == "hn":
        pts = it.metrics.get("points", 0)
        return min(math.log1p(pts / age_h * 24), 3.0)
    return max(0.3, 1.5 - age_h / 48)

def score_items(items: list[Item], profile: dict, settings: dict, now: float | None = None) -> tuple[list[Item], int]:
    now = now or time.time()
    groups = {**profile.get("products", {}), **profile.get("domains", {})}
    for it in items:
        pts, matched = 0, []
        for name, spec in groups.items():
            if _topic_hits(it.title_norm, spec.get("topics", [])):
                pts += _WEIGHT_POINTS.get(spec.get("weight", "low"), 1)
                matched.append(name)
        if pts == 0 and it.source.startswith("gh:"):
            pts = 1  # pinned repo = explicit interest
        it.matched = matched
        it.score = (0.5 + min(pts, 6)) * _TRUST_MULT.get(it.trust, 1.0) * (0.5 + _velocity(it, now))
    threshold = settings["quiet_score_threshold"]
    kept = sorted((i for i in items if i.score >= threshold), key=lambda i: -i.score)
    suppressed = sum(1 for i in items if i.score < threshold)
    return kept[: settings["top_k"]], suppressed
