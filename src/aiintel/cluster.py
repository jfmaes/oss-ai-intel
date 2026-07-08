from __future__ import annotations
from aiintel.ledger import Ledger
from aiintel.models import Item

_TRUST_RANK = {"vendor": 3, "curated": 2, "community": 1}

def stories_payload(ledger: Ledger, grouped: dict[int, list[Item]]) -> tuple[list[dict], dict[int, dict]]:
    stories = []
    for sid, items in grouped.items():
        best = max(items, key=lambda i: i.score)
        sources = sorted({i.source for i in items})
        corro = max(ledger.story_corroboration(sid), len(sources))
        matched = sorted({m for i in items for m in i.matched})
        stories.append({
            "id": sid, "title": best.title, "url": best.url_canon or best.url,
            "source": ", ".join(sources),
            "trust": max(items, key=lambda i: _TRUST_RANK.get(i.trust, 0)).trust,
            "score": round(best.score + 0.5 * (corro - 1), 1),
            "matched": matched, "metrics": {"corroboration": corro},
            "prior_briefings": ledger.story_prior_briefings(sid)})
    stories.sort(key=lambda s: -s["score"])
    return stories, {s["id"]: s for s in stories}
