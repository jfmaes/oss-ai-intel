import time
from aiintel.ledger import Ledger
from aiintel.models import Item

def _item(url, title):
    it = Item(url=url, title=title, source="hn", trust="community", published=time.time(), metrics={})
    it.url_canon, it.title_norm = url, title.lower()
    return it

def test_exact_url_dupe_filtered(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    a = _item("https://x.com/a", "First story")
    led.insert_items([a], "2026-07-08")
    new, dupes = led.filter_new([_item("https://x.com/a", "totally different title")], 14, 92)
    assert new == [] and dupes == 1

def test_fuzzy_title_dupe_filtered(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    led.insert_items([_item("https://a.com/1", "LangGraph 2.0 released with new checkpointing")], "2026-07-08")
    new, dupes = led.filter_new([_item("https://b.com/2", "LangGraph 2.0 released — new checkpointing")], 14, 92)
    assert new == [] and dupes == 1

def test_fresh_item_passes(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    led.insert_items([_item("https://a.com/1", "Old news")], "2026-07-08")
    new, dupes = led.filter_new([_item("https://c.com/3", "Completely unrelated breakthrough")], 14, 92)
    assert len(new) == 1 and dupes == 0

def test_same_batch_url_dupe_filtered(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    a = _item("https://x.com/a", "Completely unrelated headline one")
    b = _item("https://x.com/a", "Different words entirely about something else")
    new, dupes = led.filter_new([a, b], 14, 92)
    assert len(new) == 1 and dupes == 1

def test_brief_log_and_last_success(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    assert led.last_success() is None
    led.record_brief("2026-07-08", "daily", "[intel] 2026-07-08 — 1 ACT · 3 SIGNAL", 0.31, {"collected": 10})
    assert led.last_success() is not None
    ts_after_daily = led.last_success()
    led.record_brief("2026-07-08", "failed", "[intel] FAILED — collect", 0.0, {})
    rows = led.conn.execute("select kind from brief_log").fetchall()
    assert len(rows) == 2
    assert led.last_success() == ts_after_daily
