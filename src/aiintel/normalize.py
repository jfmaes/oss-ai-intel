from __future__ import annotations
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from aiintel.models import Item

_TRACKING = {"ref", "fbclid", "gclid", "source"}
_ARXIV = re.compile(r"^https://(?:[a-z0-9-]+\.)?arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})")
_GH = re.compile(r"^https://github\.com/([^/]+)/([^/]+)")
_GH_RESERVED = {"orgs", "topics", "marketplace", "sponsors", "settings", "apps",
                "collections", "features", "trending", "explore", "about",
                "enterprise", "pricing", "login", "join", "search", "new",
                "notifications", "issues", "pulls"}

def canonical_url(url: str) -> str:
    s = urlsplit(url.strip())
    host = s.netloc.lower().removeprefix("www.")
    q = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True)
         if not k.startswith("utm_") and k not in _TRACKING]
    path = s.path.rstrip("/")
    if host == "github.com":
        path = path.lower()
    return urlunsplit((s.scheme.lower() or "https", host, path, urlencode(q), ""))

def natural_key(url_canon: str, title: str) -> str:
    m = _ARXIV.match(url_canon)
    if m:
        return f"arxiv:{m.group(1)}"
    m = _GH.match(url_canon)
    if m and m.group(1) not in _GH_RESERVED:
        return f"gh:{m.group(1)}/{m.group(2)}"
    return ""

def norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().lower()

def normalize(items: list[Item]) -> list[Item]:
    out = []
    for it in items:
        if not it.url or not it.title:
            continue
        it.url_canon = canonical_url(it.url)
        it.title_norm = norm_title(it.title)
        it.natural_key = natural_key(it.url_canon, it.title)
        out.append(it)
    return out
