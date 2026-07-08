from __future__ import annotations
import sys, time
from calendar import timegm
import feedparser
import requests
from aiintel.models import Item

def collect(cfg, http_get=None) -> list[Item]:
    get = http_get or requests.get
    cutoff = time.time() - cfg.settings["lookback_hours"] * 3600
    items = []
    for repo in cfg.sources["github_releases"]["repos"]:
        try:
            body = get(f"https://github.com/{repo}/releases.atom", timeout=30).text
            for e in feedparser.parse(body).entries:
                t = e.get("updated_parsed") or e.get("published_parsed")
                if not t or timegm(t) < cutoff:
                    continue
                items.append(Item(
                    url=e.get("link") or f"https://github.com/{repo}/releases",
                    title=f"{repo} release: {e.get('title', '')}",
                    source=f"gh:{repo}", trust="vendor",
                    published=float(timegm(t)), metrics={}))
        except Exception as exc:
            print(f"[gh] {repo} failed: {exc}", file=sys.stderr)
    return items
