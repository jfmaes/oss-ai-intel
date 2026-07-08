import json, time, types, pytest
from pathlib import Path
from aiintel import analyst
from aiintel.engines import EngineError
from aiintel.models import Item

ROOT = Path(__file__).resolve().parents[1]

def _items(n=3):
    out = []
    for i in range(n):
        it = Item(url=f"https://s{i}.com", title=f"Story {i}", source="hn", trust="community",
                  published=time.time(), metrics={"points": 100 - i})
        it.url_canon, it.title_norm, it.score = it.url, it.title.lower(), 10.0 - i
        out.append(it)
    return out

def _payload():
    return analyst.build_payload("2026-07-08", _items(), [11, 12, 13],
                                 {"collected": 5, "suppressed_dupes": 1, "below_threshold": 1},
                                 {"products": {}})

GOOD = {"act": [{"story_id": 11, "headline": "H", "why_it_matters": "W", "product_refs": ["my-agent-app"],
                 "action": "evaluate", "links": ["https://s0.com"]}],
        "signal": [{"story_id": 12, "line": "L"}], "merges": [], "materiality_notes": {}, "near_miss": 13}

def test_build_payload_shape():
    p = _payload()
    assert p["date"] == "2026-07-08"
    assert [s["id"] for s in p["stories"]] == [11, 12, 13]
    assert p["stories"][0]["prior_briefings"] == []
    assert p["stats"]["collected"] == 5

def test_validate_good_passes():
    out = analyst.validate_output(json.loads(json.dumps(GOOD)), {11, 12, 13}, {"act_max": 2, "signal_max": 7})
    assert out["act"][0]["story_id"] == 11 and out["near_miss"] == 13

def test_validate_drops_unknown_ids_and_truncates():
    bad = json.loads(json.dumps(GOOD))
    bad["signal"].append({"story_id": 999, "line": "ghost"})
    bad["act"].append({"story_id": 12, "headline": "x", "why_it_matters": "y",
                       "product_refs": ["my-rag-app"], "action": "watch", "links": []})
    bad["act"].append({"story_id": 13, "headline": "x", "why_it_matters": "y",
                       "product_refs": ["my-agent-app"], "action": "watch", "links": []})
    out = analyst.validate_output(bad, {11, 12, 13}, {"act_max": 2, "signal_max": 7})
    assert len(out["act"]) == 2
    assert all(s["story_id"] != 999 for s in out["signal"])

def test_validate_rejects_empty_product_refs():
    bad = json.loads(json.dumps(GOOD))
    bad["act"][0]["product_refs"] = []
    with pytest.raises(ValueError):
        analyst.validate_output(bad, {11, 12, 13}, {"act_max": 2, "signal_max": 7})

def test_validate_rejects_rementioned_prior_without_note():
    # I4: a re-mention of a story that has prior_briefings must carry a note.
    out = json.loads(json.dumps(GOOD))  # act 11, signal 12, no materiality_notes
    with pytest.raises(ValueError):
        analyst.validate_output(out, {11, 12, 13},
                                {"act_max": 2, "signal_max": 7}, prior_ids={11})

def test_validate_rejects_rementioned_prior_signal_without_note():
    out = json.loads(json.dumps(GOOD))
    with pytest.raises(ValueError):
        analyst.validate_output(out, {11, 12, 13},
                                {"act_max": 2, "signal_max": 7}, prior_ids={12})

def test_validate_allows_rementioned_prior_with_note():
    out = json.loads(json.dumps(GOOD))
    out["materiality_notes"] = {"11": "security impact confirmed"}
    res = analyst.validate_output(out, {11, 12, 13},
                                  {"act_max": 2, "signal_max": 7}, prior_ids={11})
    assert res["act"][0]["story_id"] == 11
    assert res["materiality_notes"]["11"] == "security impact confirmed"

def test_validate_bad_action_raises():
    bad = json.loads(json.dumps(GOOD))
    bad["act"][0]["action"] = "panic"
    with pytest.raises(ValueError):
        analyst.validate_output(bad, {11, 12, 13}, {"act_max": 2, "signal_max": 7})

def test_run_analyst_repair_retry(monkeypatch):
    calls = []
    def fake_engine_run(prompt, timeout=300):
        calls.append(prompt)
        if len(calls) == 1:
            return "garbage no json", 0.1
        return json.dumps(GOOD), 0.2
    fake_mod = types.SimpleNamespace(run=fake_engine_run)
    monkeypatch.setattr(analyst, "get_engine", lambda name: fake_mod)
    out, cost = analyst.run_analyst(_payload(), "claude", ROOT / "prompts",
                                    {"act_max": 2, "signal_max": 7, "analyst_timeout_seconds": 300})
    assert out["act"][0]["story_id"] == 11
    assert len(calls) == 2 and "VALIDATION ERROR" in calls[1]
    assert cost == pytest.approx(0.3)

def test_run_analyst_double_failure_raises(monkeypatch):
    fake_mod = types.SimpleNamespace(run=lambda p, timeout=300: ("still garbage", 0.1))
    monkeypatch.setattr(analyst, "get_engine", lambda name: fake_mod)
    with pytest.raises(analyst.AnalystError):
        analyst.run_analyst(_payload(), "claude", ROOT / "prompts",
                            {"act_max": 2, "signal_max": 7, "analyst_timeout_seconds": 300})

def test_fallback_brief_shape():
    fb = analyst.fallback_brief(_payload(), {"signal_max": 7})
    assert fb["act"] == [] and fb["fallback"] is True
    assert fb["signal"][0]["story_id"] == 11

def test_run_analyst_engine_crash_raises_analyst_error(monkeypatch):
    def boom(prompt, timeout=300):
        raise EngineError("claude engine: claude -p exit 1: transient")
    monkeypatch.setattr(analyst, "get_engine", lambda n: types.SimpleNamespace(run=boom))
    with pytest.raises(analyst.AnalystError):
        analyst.run_analyst(_payload(), "claude", ROOT / "prompts",
                            {"act_max": 2, "signal_max": 7, "analyst_timeout_seconds": 300})

def test_run_analyst_engine_error_twice_raises_analyst_error(monkeypatch):
    # C1: a missing/broken binary surfaces as EngineError on every attempt;
    # after two the analyst gives up cleanly so daily() reaches the fallback.
    def no_binary(prompt, timeout=300):
        raise EngineError("no such binary")
    monkeypatch.setattr(analyst, "get_engine", lambda n: types.SimpleNamespace(run=no_binary))
    with pytest.raises(analyst.AnalystError):
        analyst.run_analyst(_payload(), "claude", ROOT / "prompts",
                            {"act_max": 2, "signal_max": 7, "analyst_timeout_seconds": 300})

def test_run_analyst_timeout_then_success(monkeypatch):
    # The real engine wrapper converts a subprocess timeout into EngineError;
    # the fake mirrors that contract so the analyst retry catches it.
    calls = []
    def flaky(prompt, timeout=300):
        calls.append(1)
        if len(calls) == 1:
            raise EngineError("claude engine: Command 'claude' timed out after 300 seconds")
        return json.dumps(GOOD), 0.2
    monkeypatch.setattr(analyst, "get_engine", lambda n: types.SimpleNamespace(run=flaky))
    out, cost = analyst.run_analyst(_payload(), "claude", ROOT / "prompts",
                                    {"act_max": 2, "signal_max": 7, "analyst_timeout_seconds": 300})
    assert out["act"][0]["story_id"] == 11 and len(calls) == 2

def test_validate_rejects_non_list_links():
    bad = json.loads(json.dumps(GOOD))
    bad["act"][0]["links"] = None
    with pytest.raises(ValueError):
        analyst.validate_output(bad, {11, 12, 13}, {"act_max": 2, "signal_max": 7})
