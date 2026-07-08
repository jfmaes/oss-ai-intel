import json, time, types
from pathlib import Path
from aiintel import run as runmod
from aiintel.models import Item

ROOT = Path(__file__).resolve().parents[1]

def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_INTEL_ROOT", str(ROOT))
    monkeypatch.setattr(runmod, "_state_root", lambda root: tmp_path)

def _mk(url, title, key="", source="hn"):
    return Item(url=url, title=title, source=source, trust="community",
                published=time.time(), metrics={"points": 400})

def _engine_echo_first_as_act(monkeypatch):
    def fake_run(prompt, timeout=300):
        payload = json.loads(prompt.split("## INPUT\n```json\n", 1)[1].rsplit("\n```", 1)[0])
        s = payload["stories"][0]
        pb = s["prior_briefings"]
        if pb:  # already told: obey materiality rule, stay silent
            return json.dumps({"act": [], "signal": [], "merges": [],
                               "materiality_notes": {}, "near_miss": None}), 0.01
        return json.dumps({"act": [{"story_id": s["id"], "headline": s["title"][:80],
                                    "why_it_matters": "Affects my-agent-app's orchestration layer.",
                                    "product_refs": ["my-agent-app"], "action": "evaluate",
                                    "links": [s["url"]]}],
                           "signal": [], "merges": [], "materiality_notes": {},
                           "near_miss": None}), 0.01
    from aiintel import analyst
    monkeypatch.setattr(analyst, "get_engine", lambda n: types.SimpleNamespace(run=fake_run))

def test_multisource_event_briefs_once_then_silent(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _engine_echo_first_as_act(monkeypatch)
    # day 1: two sources, same natural key → ONE story → one ACT
    # (titles carry "mcp" — a real profile.yaml topic — so the item clears
    # quiet_score_threshold and reaches the analyst; a title with zero topic hits
    # can never pass score_items regardless of story wiring, deviation from brief noted in report)
    day1 = {"c": lambda cfg, http_get=None: [
        _mk("https://github.com/org/repo/releases/tag/v2", "org/repo release: v2 adds mcp support", source="gh:org/repo"),
        _mk("https://news.ycombinator.com/item?id=1", "org/repo release: v2 discussion", source="hn")]}
    assert runmod.daily(ROOT, dry_run=True, collectors_map=day1) == 0
    txt1 = sorted((tmp_path / "briefs").glob("*.txt"))[-1].read_text()
    assert txt1.count("org/repo release") == 1 and "ACT" in txt1
    # day 2: same event resurfaces via a NEW github url (same natural key, title
    # fuzzy-far so link-dedupe does NOT catch it) → story known, prior_briefings
    # non-empty → analyst stays silent → all quiet. Exercises the materiality gate.
    day2 = {"c": lambda cfg, http_get=None: [
        _mk("https://github.com/org/repo/releases/tag/v2.0.1",
            "Critical mcp patch lands after the big launch", source="rss:other")]}
    assert runmod.daily(ROOT, dry_run=True, collectors_map=day2) == 0
    txt2 = sorted((tmp_path / "briefs").glob("*.txt"))[-1].read_text()
    assert "all quiet" in txt2

def test_merge_remaps_briefing_to_kept_story(tmp_path, monkeypatch):
    # I2: analyst merges two stories and briefs under the dupe's id; the briefing
    # must land on the KEPT story, never orphaned under the merged-away one.
    _isolate(tmp_path, monkeypatch)
    def fake_run(prompt, timeout=300):
        payload = json.loads(prompt.split("## INPUT\n```json\n", 1)[1].rsplit("\n```", 1)[0])
        ids = [s["id"] for s in payload["stories"]]
        keep, dupe = ids[0], ids[1]
        out = {"act": [], "signal": [{"story_id": dupe, "line": "one merged signal"}],
               "merges": [[keep, dupe]], "materiality_notes": {}, "near_miss": None}
        return json.dumps(out), 0.01
    from aiintel import analyst
    monkeypatch.setattr(analyst, "get_engine", lambda n: types.SimpleNamespace(run=fake_run))
    cols = {"c": lambda cfg, http_get=None: [
        _mk("https://fresh.com/rr", "A new reranker architecture drops"),
        _mk("https://fresh.com/mcp", "MCP server registry launches today")]}
    assert runmod.daily(ROOT, dry_run=True, collectors_map=cols) == 0
    from aiintel.ledger import Ledger
    with Ledger(tmp_path / "ledger.sqlite") as led:
        stories = led.conn.execute("SELECT id FROM stories").fetchall()
        assert len(stories) == 1                             # dupe merged away
        keep_id = stories[0][0]
        rows = led.conn.execute("SELECT story_id FROM story_briefings").fetchall()
        assert rows and all(r[0] == keep_id for r in rows)   # briefing on the KEPT story

def test_double_dupe_merge_never_orphans_briefing(tmp_path, monkeypatch):
    # final-review verification: analyst emits merges=[[A,B],[C,B]] — B is claimed
    # as a dupe by two different keepers in the same run — and briefs under A,
    # which the second pair then itself absorbs into C. run.py's `resolved` map
    # must follow that transitively (same as ledger.apply_merges does internally),
    # or the mark_briefed insert lands on A after A has been deleted from `stories`.
    _isolate(tmp_path, monkeypatch)
    def fake_run(prompt, timeout=300):
        payload = json.loads(prompt.split("## INPUT\n```json\n", 1)[1].rsplit("\n```", 1)[0])
        a, b, c = sorted(s["id"] for s in payload["stories"])
        out = {"act": [], "signal": [{"story_id": a, "line": "signal under a story merged away twice"}],
               "merges": [[a, b], [c, b]], "materiality_notes": {}, "near_miss": None}
        return json.dumps(out), 0.01
    from aiintel import analyst
    monkeypatch.setattr(analyst, "get_engine", lambda n: types.SimpleNamespace(run=fake_run))
    cols = {"c": lambda cfg, http_get=None: [
        _mk("https://fresh.com/rr", "A new reranker architecture drops"),
        _mk("https://fresh.com/mcp", "MCP server registry launches today"),
        _mk("https://fresh.com/swe", "Autonomous coding harness passes swe-bench today")]}
    assert runmod.daily(ROOT, dry_run=True, collectors_map=cols) == 0
    from aiintel.ledger import Ledger
    with Ledger(tmp_path / "ledger.sqlite") as led:
        story_ids = {r[0] for r in led.conn.execute("SELECT id FROM stories").fetchall()}
        assert len(story_ids) == 1                              # both dupes merged away
        survivor = next(iter(story_ids))
        briefing_story_ids = [r[0] for r in led.conn.execute(
            "SELECT story_id FROM story_briefings").fetchall()]
        assert briefing_story_ids                                # sanity: something was briefed
        assert all(sid in story_ids for sid in briefing_story_ids)  # no orphaned rows
        assert all(sid == survivor for sid in briefing_story_ids)   # history landed on the survivor

def test_update_prefix_on_rebrief(tmp_path, monkeypatch):
    from aiintel.render import render
    stories = {5: {"id": 5, "title": "T", "url": "https://x", "source": "hn",
                   "prior_briefings": [{"date": "2026-07-07", "section": "act", "line": "old"}]}}
    out = {"act": [{"story_id": 5, "headline": "T got worse", "why_it_matters": "w",
                    "product_refs": ["my-agent-app"], "action": "watch", "links": []}],
           "signal": [], "merges": [], "materiality_notes": {"5": "security impact"},
           "near_miss": None, "fallback": False}
    b = render("2026-07-08", out, stories, {"collected": 1, "suppressed_dupes": 0, "below_threshold": 0}, {})
    assert "UPDATE: T got worse" in b.text
