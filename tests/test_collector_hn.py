import time, types
from aiintel.collectors import hn

def _resp(hits):
    return types.SimpleNamespace(json=lambda: {"hits": hits}, raise_for_status=lambda: None)

def _fake_get(responses):
    calls = []
    def get(url, params=None, timeout=30):
        calls.append((url, params))
        return responses.pop(0)
    return get, calls

def _cfg():
    return types.SimpleNamespace(
        settings={"lookback_hours": 36},
        sources={"hn": {"min_points_search": 80}})

def test_collects_and_dedupes_across_calls():
    now = int(time.time())
    front = [{"objectID": "1", "title": "A", "url": "https://a.com", "points": 100, "num_comments": 5, "created_at_i": now}]
    search = [{"objectID": "1", "title": "A", "url": "https://a.com", "points": 100, "num_comments": 5, "created_at_i": now},
              {"objectID": "2", "title": "B", "url": None, "points": 90, "num_comments": 1, "created_at_i": now}]
    get, calls = _fake_get([_resp(front), _resp(search)])
    items = hn.collect(_cfg(), http_get=get)
    assert len(items) == 2
    assert items[1].url == "https://news.ycombinator.com/item?id=2"
    assert items[0].metrics["points"] == 100
    assert all(i.source == "hn" and i.trust == "community" for i in items)

def test_numeric_filters_in_params_not_url():
    now = int(time.time())
    get, calls = _fake_get([_resp([]), _resp([])])
    hn.collect(_cfg(), http_get=get)
    url, params = calls[1]
    assert "numericFilters" in params and ">" in params["numericFilters"]
    assert ">" not in url

def test_one_call_failing_keeps_other_results():
    now = int(time.time())
    search = [{"objectID": "7", "title": "Survivor", "url": "https://s.com", "points": 90, "num_comments": 1, "created_at_i": now}]
    def get(url, params=None, timeout=30):
        if "search_by_date" not in url:
            raise RuntimeError("front page down")
        return _resp(search)
    items = hn.collect(_cfg(), http_get=get)
    assert len(items) == 1 and items[0].title == "Survivor"
