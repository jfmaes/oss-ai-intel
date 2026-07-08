from __future__ import annotations
import sys
import time
import requests
from aiintel.models import Item

API = "https://hn.algolia.com/api/v1/search"
API_BY_DATE = "https://hn.algolia.com/api/v1/search_by_date"

def collect(cfg, http_get=None) -> list[Item]:
    get = http_get or requests.get
    cutoff = int(time.time()) - cfg.settings["lookback_hours"] * 3600
    min_pts = cfg.sources["hn"]["min_points_search"]
    calls = [
        (API, {"tags": "front_page", "hitsPerPage": "50"}),
        (API_BY_DATE, {
            "tags": "story",
            "numericFilters": f"points>{min_pts},created_at_i>{cutoff}",
            "hitsPerPage": "100"}),
    ]
    seen, items = set(), []
    for url, params in calls:
        try:
            resp = get(url, params=params, timeout=30)
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        except Exception as exc:
            print(f"[hn] {url} failed: {exc}", file=sys.stderr)
            continue
        for h in hits:
            oid = h.get("objectID")
            if not oid or oid in seen:
                continue
            seen.add(oid)
            items.append(Item(
                url=h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                title=h.get("title") or "",
                source="hn", trust="community",
                published=float(h.get("created_at_i") or time.time()),
                metrics={"points": h.get("points") or 0, "comments": h.get("num_comments") or 0}))
    return items
