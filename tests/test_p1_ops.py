import time, types
from pathlib import Path
from aiintel import run as runmod

ROOT = Path(__file__).resolve().parents[1]

def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_INTEL_ROOT", str(ROOT))
    monkeypatch.setattr(runmod, "_state_root", lambda root: tmp_path)

def test_daily_safe_failure_writes_failed_brief(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    def boom_collectors():
        raise RuntimeError("total collapse")
    monkeypatch.setattr(runmod, "all_collectors", boom_collectors)
    rc = runmod.daily_safe(ROOT, dry_run=True)
    assert rc == 1
    failed = list((tmp_path / "briefs").glob("*-FAILED.html"))
    assert len(failed) == 1 and "total collapse" in failed[0].read_text()

def test_guard_runs_when_stale_and_skips_when_fresh(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(runmod, "daily_safe", lambda root, **kw: calls.append(1) or 0)
    assert runmod.guard(ROOT) == 0
    assert calls == [1]  # no ledger yet → stale → ran
    from aiintel.ledger import Ledger
    with Ledger(tmp_path / "ledger.sqlite") as led:
        led.record_brief("2026-07-08", "daily", "s", 0.0, {})
    assert runmod.guard(ROOT) == 0
    assert calls == [1]  # fresh → not run again

def test_doctor_reports(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(runmod, "_head_ok", lambda url: True)
    monkeypatch.setattr(runmod, "load_secrets", lambda: {"INTEL_SMTP_APP_PASSWORD": "x"})
    monkeypatch.setattr(runmod, "_which_claude", lambda: True)
    monkeypatch.setattr(runmod, "_cron_line_count", lambda: 3)
    monkeypatch.setattr(runmod, "_secrets_perms_ok", lambda: True)
    assert runmod.doctor(ROOT) == 0
    out = capsys.readouterr().out
    assert "PASS config" in out and "PASS secrets" in out
    assert "PASS engine" in out and "PASS cron" in out and "PASS secrets-perms" in out

def test_doctor_flags_missing_engine_and_cron(tmp_path, monkeypatch, capsys):
    # M3: doctor must catch the cron-class failures (no claude on PATH, no cron rows).
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(runmod, "_head_ok", lambda url: True)
    monkeypatch.setattr(runmod, "load_secrets", lambda: {"INTEL_SMTP_APP_PASSWORD": "x"})
    monkeypatch.setattr(runmod, "_which_claude", lambda: False)
    monkeypatch.setattr(runmod, "_cron_line_count", lambda: 0)
    monkeypatch.setattr(runmod, "_secrets_perms_ok", lambda: None)  # no file → skipped
    assert runmod.doctor(ROOT) == 1
    out = capsys.readouterr().out
    assert "FAIL engine" in out and "FAIL cron" in out
    assert "secrets-perms" not in out  # skipped entirely when the file is absent

def test_daily_safe_html_escapes_traceback(tmp_path, monkeypatch):
    # M1: exception text must be HTML-escaped in the FAILED artifact/email body.
    _isolate(tmp_path, monkeypatch)
    def boom_collectors():
        raise RuntimeError("boom <script>alert(1)</script> & co")
    monkeypatch.setattr(runmod, "all_collectors", boom_collectors)
    assert runmod.daily_safe(ROOT, dry_run=True) == 1
    html = list((tmp_path / "briefs").glob("*-FAILED.html"))[0].read_text()
    assert "&lt;script&gt;" in html
    assert "<script>alert" not in html

def test_finalize_failure_suppresses_failed_notice(tmp_path, monkeypatch, capsys):
    # M2: a failure AFTER successful delivery (finalize stage) must not emit a
    # second FAILED notice — the brief already went out (one-email contract).
    _isolate(tmp_path, monkeypatch)
    from aiintel.ledger import Ledger
    def boom_record(self, *a, **k):
        raise RuntimeError("post-delivery ledger write failed")
    monkeypatch.setattr(Ledger, "record_brief", boom_record)
    cols = {"empty": lambda cfg, http_get=None: []}  # all-quiet → delivery ok → finalize
    assert runmod.daily_safe(ROOT, dry_run=True, collectors_map=cols) == 1
    htmls = list((tmp_path / "briefs").glob("*.html"))
    assert htmls and all("FAILED" not in h.name for h in htmls)  # brief written, no FAILED
    assert "finalize" in capsys.readouterr().err.lower()

def test_daily_safe_nondryrun_cascading_failure_records_failed_row(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    def boom_collectors():
        raise RuntimeError("primary failure")
    monkeypatch.setattr(runmod, "all_collectors", boom_collectors)
    monkeypatch.setattr(runmod, "load_secrets", lambda: {})  # send will raise missing-password
    rc = runmod.daily_safe(ROOT, dry_run=False)
    assert rc == 1
    err = capsys.readouterr().err
    assert "primary failure" in err                      # original tb printed
    assert "could not deliver failure notice" in err     # secondary failure noted distinctly
    from aiintel.ledger import Ledger
    with Ledger(tmp_path / "ledger.sqlite") as led:
        rows = led.conn.execute("SELECT kind, subject FROM brief_log").fetchall()
    assert rows and rows[-1][0] == "failed" and "FAILED" in rows[-1][1]

def test_daily_safe_dryrun_artifact_names_stage(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    def boom_collectors():
        raise RuntimeError("stage naming check")
    monkeypatch.setattr(runmod, "all_collectors", boom_collectors)
    assert runmod.daily_safe(ROOT, dry_run=True) == 1
    failed = list((tmp_path / "briefs").glob("*-FAILED.html"))[0].read_text()
    assert "FAILED — collect" in failed                  # stage visible in artifact
