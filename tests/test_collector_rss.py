import time, types, email.utils
from aiintel.collectors import rss

def _atom(entry_age_hours):
    dt = email.utils.formatdate(time.time() - entry_age_hours * 3600)
    return f"""<?xml version="1.0"?><rss version="2.0"><channel><title>F</title>
    <item><title>Fresh post</title><link>https://f.com/fresh</link><pubDate>{dt}</pubDate></item>
    </channel></rss>"""

def _cfg(feeds):
    return types.SimpleNamespace(settings={"lookback_hours": 36}, sources={"rss": {"feeds": feeds}})

def _get_for(bodies):
    def get(url, timeout=30):
        body = bodies[url]
        if isinstance(body, Exception):
            raise body
        return types.SimpleNamespace(text=body, raise_for_status=lambda: None)
    return get

def test_fresh_entry_collected_stale_dropped():
    feeds = [{"name": "a", "url": "https://a/f", "trust": "curated"}]
    items = rss.collect(_cfg(feeds), http_get=_get_for({"https://a/f": _atom(2)}))
    assert len(items) == 1 and items[0].source == "rss:a" and items[0].trust == "curated"
    items = rss.collect(_cfg(feeds), http_get=_get_for({"https://a/f": _atom(100)}))
    assert items == []

def test_broken_feed_skipped_not_fatal():
    feeds = [{"name": "bad", "url": "https://bad/f", "trust": "vendor"},
             {"name": "ok", "url": "https://ok/f", "trust": "vendor"}]
    items = rss.collect(_cfg(feeds), http_get=_get_for({
        "https://bad/f": RuntimeError("boom"), "https://ok/f": _atom(1)}))
    assert len(items) == 1 and items[0].source == "rss:ok"

def test_http_error_status_is_isolated_with_note(capsys):
    feeds = [{"name": "dead", "url": "https://dead/f", "trust": "vendor"},
             {"name": "ok", "url": "https://ok/f", "trust": "vendor"}]
    def get(url, timeout=30):
        if url == "https://dead/f":
            def boom():
                raise RuntimeError("404 Client Error")
            return types.SimpleNamespace(text="<html>not found</html>", raise_for_status=boom)
        return types.SimpleNamespace(text=_atom(1), raise_for_status=lambda: None)
    items = rss.collect(_cfg(feeds), http_get=get)
    assert len(items) == 1 and items[0].source == "rss:ok"
    assert "dead" in capsys.readouterr().err
