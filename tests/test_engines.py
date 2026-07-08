import json, pytest
from aiintel import engines

def test_get_engine_unknown_raises():
    with pytest.raises(ValueError):
        engines.get_engine("nonexistent")

def test_get_engine_claude_has_run():
    assert callable(engines.get_engine("claude").run)

def test_extract_json_plain():
    assert engines.extract_json('{"a": 1}') == {"a": 1}

def test_extract_json_fenced_with_prose():
    text = 'Here you go:\n```json\n{"act": [], "signal": []}\n```\nDone.'
    assert engines.extract_json(text) == {"act": [], "signal": []}

def test_extract_json_garbage_raises():
    with pytest.raises(ValueError):
        engines.extract_json("no json here")

def test_claude_run_parses_envelope(monkeypatch):
    from aiintel.engines import claude as ce
    class P:
        returncode = 0
        stdout = json.dumps({"type": "result", "is_error": False,
                             "result": '{"ok": true}', "total_cost_usd": 0.42})
        stderr = ""
    monkeypatch.setattr(ce.subprocess, "run", lambda *a, **k: P())
    text, cost = ce.run("prompt")
    assert text == '{"ok": true}' and cost == 0.42

def test_claude_run_nonzero_exit_raises_engine_error(monkeypatch):
    from aiintel.engines import claude as ce
    class P:
        returncode = 2
        stdout = ""
        stderr = "boom"
    monkeypatch.setattr(ce.subprocess, "run", lambda *a, **k: P())
    with pytest.raises(engines.EngineError):
        ce.run("prompt")

def test_claude_run_is_error_raises_engine_error(monkeypatch):
    from aiintel.engines import claude as ce
    class P:
        returncode = 0
        stdout = json.dumps({"is_error": True, "result": "model refused"})
        stderr = ""
    monkeypatch.setattr(ce.subprocess, "run", lambda *a, **k: P())
    with pytest.raises(engines.EngineError):
        ce.run("prompt")

def test_claude_run_timeout_wrapped_as_engine_error(monkeypatch):
    import subprocess as sp
    from aiintel.engines import claude as ce
    def boom(*a, **k):
        raise sp.TimeoutExpired(cmd="claude", timeout=1)
    monkeypatch.setattr(ce.subprocess, "run", boom)
    with pytest.raises(engines.EngineError):
        ce.run("prompt")

def test_claude_run_missing_binary_wrapped_as_engine_error(monkeypatch):
    from aiintel.engines import claude as ce
    def boom(*a, **k):
        raise FileNotFoundError("no such binary: claude")
    monkeypatch.setattr(ce.subprocess, "run", boom)
    with pytest.raises(engines.EngineError):
        ce.run("prompt")

def test_claude_run_bad_json_wrapped_as_engine_error(monkeypatch):
    from aiintel.engines import claude as ce
    class P:
        returncode = 0
        stdout = "not json at all"
        stderr = ""
    monkeypatch.setattr(ce.subprocess, "run", lambda *a, **k: P())
    with pytest.raises(engines.EngineError):
        ce.run("prompt")
