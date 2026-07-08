import time, types
from aiintel.collectors import github_releases, all_collectors

def _atom(age_h):
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age_h * 3600))
    return f"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
    <entry><title>v2.0.0</title><link href="https://github.com/o/r/releases/tag/v2.0.0"/>
    <updated>{iso}</updated></entry></feed>"""

def _cfg(repos):
    return types.SimpleNamespace(settings={"lookback_hours": 36},
                                 sources={"github_releases": {"repos": repos}})

def test_release_item_shape():
    get = lambda url, timeout=30: types.SimpleNamespace(text=_atom(3), raise_for_status=lambda: None)
    items = github_releases.collect(_cfg(["o/r"]), http_get=get)
    assert len(items) == 1
    it = items[0]
    assert it.title == "o/r release: v2.0.0" and it.source == "gh:o/r" and it.trust == "vendor"
    assert it.url == "https://github.com/o/r/releases/tag/v2.0.0"

def test_registry_lists_three():
    assert set(all_collectors()) == {"hn", "rss", "github_releases"}
