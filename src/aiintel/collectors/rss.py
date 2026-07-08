from __future__ import annotations
import sys, time
from calendar import timegm
import feedparser
import requests
from aiintel.models import Item

def _entry_ts(e) -> float | None:
    t = e.get("published_parsed") or e.get("updated_parsed")
    return timegm(t) if t else None

def collect(cfg, http_get=None) -> list[Item]:
    get = http_get or requests.get
    cutoff = time.time() - cfg.settings["lookback_hours"] * 3600
    items = []
    for feed in cfg.sources["rss"]["feeds"]:
        try:
            resp = get(feed["url"], timeout=30)
            resp.raise_for_status()
            body = resp.text
            parsed = feedparser.parse(body)
            for e in parsed.entries:
                ts = _entry_ts(e)
                if ts is None or ts < cutoff:
                    continue
                items.append(Item(
                    url=e.get("link") or "", title=e.get("title") or "",
                    source=f"rss:{feed['name']}", trust=feed.get("trust", "community"),
                    published=ts, metrics={}))
        except Exception as exc:
            print(f"[rss] feed {feed.get('name', feed.get('url', '?'))} failed: {exc}", file=sys.stderr)
    return items
