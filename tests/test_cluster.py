import time
from aiintel.cluster import stories_payload
from aiintel.ledger import Ledger
from aiintel.models import Item

def _item(url, title, key="", source="hn", score=5.0):
    it = Item(url=url, title=title, source=source, trust="community",
              published=time.time(), metrics={})
    it.url_canon, it.title_norm, it.natural_key, it.score = url, title.lower(), key, score
    return it

def test_natural_key_groups_across_sources(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    a = _item("https://github.com/org/repo/releases/tag/v2", "org/repo release: v2", key="gh:org/repo", source="gh:org/repo")
    grouped, _ = led.attach_stories([a])
    assert len(grouped) == 1
    sid = next(iter(grouped))
    led.insert_items([a], "2026-07-08", story_of={id(a): sid})
    b = _item("https://news.ycombinator.com/item?id=9", "org/repo release: v2 is out", key="", source="hn")
    grouped2, _ = led.attach_stories([b])
    assert next(iter(grouped2)) == sid  # fuzzy joined the same story
    led.insert_items([b], "2026-07-08", story_of={id(b): sid})
    assert led.story_corroboration(sid) == 2

def test_briefing_history_and_mark(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    grouped, _ = led.attach_stories([_item("https://a.com/x", "Fresh event", key="")])
    sid = next(iter(grouped))
    assert led.story_prior_briefings(sid) == []
    led.mark_briefed([(sid, "act", "Fresh event happened")], "2026-07-08")
    hist = led.story_prior_briefings(sid)
    assert hist[0]["section"] == "act" and hist[0]["date"] == "2026-07-08"

def test_apply_merges(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    g1, _ = led.attach_stories([_item("https://a.com/1", "Event alpha", key="", score=4.0)])
    keep = next(iter(g1))
    a2 = _item("https://b.com/2", "Completely different beta", key="", score=6.0)
    g2, _ = led.attach_stories([a2])
    dupe = next(iter(g2))
    led.insert_items([a2], "2026-07-08", story_of={id(a2): dupe})
    led.mark_briefed([(dupe, "signal", "beta briefed")], "2026-07-08")
    led.apply_merges([[keep, dupe]])
    # dupe story row gone
    assert led.conn.execute("SELECT COUNT(*) FROM stories WHERE id=?", (dupe,)).fetchone()[0] == 0
    # items repointed to keep
    assert led.conn.execute("SELECT COUNT(*) FROM items WHERE story_id=?", (keep,)).fetchone()[0] == 1
    assert led.conn.execute("SELECT COUNT(*) FROM items WHERE story_id=?", (dupe,)).fetchone()[0] == 0
    # briefing history repointed — prior_briefings survive the merge
    hist = led.story_prior_briefings(keep)
    assert [h["line"] for h in hist] == ["beta briefed"]
    # cum_score folded into keep
    keep_score = led.conn.execute("SELECT cum_score FROM stories WHERE id=?", (keep,)).fetchone()[0]
    assert keep_score >= 10.0  # 4.0 + 6.0

def test_apply_merges_resolves_chain(tmp_path):
    # I2: apply_merges([[a,b],[b,c]]) must fold c onto a even though b is gone
    # by the time the second pair is processed.
    led = Ledger(tmp_path / "l.sqlite")
    ga, _ = led.attach_stories([_item("https://a.com/1", "alpha event one", score=3.0)])
    a = next(iter(ga))
    gb, _ = led.attach_stories([_item("https://b.com/2", "beta event distinct two", score=3.0)])
    b = next(iter(gb))
    ic = _item("https://c.com/3", "gamma event distinct three", score=3.0)
    gc, _ = led.attach_stories([ic])
    c = next(iter(gc))
    led.insert_items([ic], "2026-07-08", story_of={id(ic): c})
    led.apply_merges([[a, b], [b, c]])
    assert led.conn.execute("SELECT COUNT(*) FROM items WHERE story_id=?", (a,)).fetchone()[0] == 1
    assert led.conn.execute("SELECT COUNT(*) FROM stories WHERE id IN (?, ?)", (b, c)).fetchone()[0] == 0

def test_mark_briefed_persists_note(tmp_path):
    # I4: the materiality note travels with the briefing row.
    led = Ledger(tmp_path / "l.sqlite")
    grouped, _ = led.attach_stories([_item("https://a.com/x", "Notable event", key="")])
    sid = next(iter(grouped))
    led.mark_briefed([(sid, "act", "It got worse", "security impact confirmed")], "2026-07-08")
    row = led.conn.execute("SELECT note FROM story_briefings WHERE story_id=?", (sid,)).fetchone()
    assert row[0] == "security impact confirmed"

def test_stories_payload_shape(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    grouped, _ = led.attach_stories([
        _item("https://a.com/1", "Event alpha", source="hn", score=6.0),
        ])
    stories, by_id = stories_payload(led, grouped)
    s = stories[0]
    assert s["metrics"]["corroboration"] == 1 and s["prior_briefings"] == []
    assert by_id[s["id"]] is s
