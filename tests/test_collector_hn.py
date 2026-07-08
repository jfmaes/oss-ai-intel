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

def test_recent_call_filters_by_created_not_points():
    # HN's index rejects a `points` numeric filter, so the recent-stories call must
    # filter by created_at_i only (points is applied client-side, see below).
    get, calls = _fake_get([_resp([]), _resp([])])
    hn.collect(_cfg(), http_get=get)
    url, params = calls[1]
    assert "created_at_i>" in params["numericFilters"]
    assert "points" not in params["numericFilters"]   # would 400 the API
    assert ">" not in url                              # filters go via params

def test_points_floor_applied_client_side():
    now = int(time.time())
    front = [{"objectID": "f", "title": "FrontLow", "url": "https://f.com", "points": 10, "num_comments": 0, "created_at_i": now}]
    search = [{"objectID": "hi", "title": "Popular", "url": "https://h.com", "points": 500, "num_comments": 9, "created_at_i": now},
              {"objectID": "lo", "title": "TooNew", "url": "https://l.com", "points": 3, "num_comments": 0, "created_at_i": now}]
    get, _ = _fake_get([_resp(front), _resp(search)])
    items = hn.collect(_cfg(), http_get=get)
    titles = {i.title for i in items}
    assert "FrontLow" in titles     # front_page kept despite low points (floor 0)
    assert "Popular" in titles      # recent, above the 80-point floor
    assert "TooNew" not in titles   # recent, below floor → dropped client-side

def test_one_call_failing_keeps_other_results():
    now = int(time.time())
    search = [{"objectID": "7", "title": "Survivor", "url": "https://s.com", "points": 90, "num_comments": 1, "created_at_i": now}]
    def get(url, params=None, timeout=30):
        if params.get("tags") == "front_page":
            raise RuntimeError("front page down")
        return _resp(search)
    items = hn.collect(_cfg(), http_get=get)
    assert len(items) == 1 and items[0].title == "Survivor"
