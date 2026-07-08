import json, time, types
from pathlib import Path
from aiintel import run as runmod
from aiintel.models import Item

ROOT = Path(__file__).resolve().parents[1]

GOOD = {"act": [], "signal": [{"story_id": 0, "line": "placeholder"}],
        "merges": [], "materiality_notes": {}, "near_miss": None}

def _fake_collector(items):
    return lambda cfg, http_get=None: list(items)

def _mk_item(url, title):
    return Item(url=url, title=title, source="hn", trust="community",
                published=time.time(), metrics={"points": 500})

def _fake_engine(monkeypatch):
    def fake_run(prompt, timeout=300):
        payload = json.loads(prompt.split("## INPUT\n```json\n", 1)[1].rsplit("\n```", 1)[0])
        sid = payload["stories"][0]["id"]
        out = dict(GOOD)
        out["signal"] = [{"story_id": sid, "line": "One fresh thing."}]
        return json.dumps(out), 0.05
    from aiintel import analyst
    monkeypatch.setattr(analyst, "get_engine",
                        lambda name: types.SimpleNamespace(run=fake_run))

def test_daily_dry_run_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_INTEL_ROOT", str(ROOT))
    monkeypatch.setattr(runmod, "_state_root", lambda root: tmp_path)
    _fake_engine(monkeypatch)
    cols = {"fake": _fake_collector([_mk_item("https://fresh.com/a", "A new reranker drops")])}
    rc = runmod.daily(ROOT, dry_run=True, collectors_map=cols)
    assert rc == 0
    briefs = list((tmp_path / "briefs").glob("*.html"))
    assert len(briefs) == 1 and "SIGNAL" in briefs[0].read_text()

def test_second_run_is_all_quiet(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_INTEL_ROOT", str(ROOT))
    monkeypatch.setattr(runmod, "_state_root", lambda root: tmp_path)
    _fake_engine(monkeypatch)
    cols = {"fake": _fake_collector([_mk_item("https://fresh.com/a", "A new reranker drops")])}
    assert runmod.daily(ROOT, dry_run=True, collectors_map=cols) == 0
    assert runmod.daily(ROOT, dry_run=True, collectors_map=cols) == 0
    txts = sorted((tmp_path / "briefs").glob("*.txt"))
    assert "all quiet" in txts[-1].read_text()  # same items → deduped → quiet

def test_collector_crash_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_INTEL_ROOT", str(ROOT))
    monkeypatch.setattr(runmod, "_state_root", lambda root: tmp_path)
    _fake_engine(monkeypatch)
    def boom(cfg, http_get=None):
        raise RuntimeError("api down")
    cols = {"boom": boom,
            "ok": _fake_collector([_mk_item("https://fresh.com/b", "Agent orchestration news")])}
    assert runmod.daily(ROOT, dry_run=True, collectors_map=cols) == 0

def test_delivery_failure_compensates_and_rebriefs(tmp_path, monkeypatch):
    # I1: delivery is the commit point. A send that raises must un-see the run's
    # items (and drop the ghost story) so the guard's retry genuinely re-briefs.
    monkeypatch.setenv("AI_INTEL_ROOT", str(ROOT))
    monkeypatch.setattr(runmod, "_state_root", lambda root: tmp_path)
    _fake_engine(monkeypatch)
    def boom_send(*a, **k):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(runmod, "send", boom_send)  # run.py imports send directly
    cols = {"fake": _fake_collector([_mk_item("https://fresh.com/z", "A new reranker drops")])}
    # non-dry-run so delivery goes through send() and fails
    assert runmod.daily_safe(ROOT, dry_run=False, collectors_map=cols) == 1
    from aiintel.ledger import Ledger
    with Ledger(tmp_path / "ledger.sqlite") as led:
        assert led.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0     # un-seen
        assert led.conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0] == 0   # no ghost story
    # the SAME collector output now briefs for real (items were never committed)
    assert runmod.daily(ROOT, dry_run=True, collectors_map=cols) == 0
    txt = sorted((tmp_path / "briefs").glob("*.txt"))[-1].read_text()
    assert "all quiet" not in txt and "SIGNAL" in txt
