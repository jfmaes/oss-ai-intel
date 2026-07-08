from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class Item:
    url: str
    title: str
    source: str        # "hn" | "rss:<name>" | "gh:<owner>/<repo>"
    trust: str         # "vendor" | "curated" | "community"
    published: float   # unix timestamp
    metrics: dict
    url_canon: str = ""
    title_norm: str = ""
    natural_key: str = ""
    score: float = 0.0
    matched: list[str] = field(default_factory=list)
