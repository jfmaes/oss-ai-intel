import pytest
from aiintel.mail import send, write_dry_run
from aiintel.render import Brief

BRIEF = Brief(subject="[intel] 2026-07-08 — all quiet", html="<p>hi</p>", text="hi")
MAIL = {"to": "me@x.com", "from": "me@x.com", "smtp_host": "smtp.gmail.com", "smtp_port": 465}

class FakeSMTP:
    sent = []
    last_kwargs = None
    def __init__(self, host, port, timeout=None, context=None):
        FakeSMTP.last_kwargs = {"timeout": timeout, "context": context}
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def login(self, user, pw): self.creds = (user, pw)
    def send_message(self, msg): FakeSMTP.sent.append(msg)

def test_send_builds_multipart_and_logs_in():
    FakeSMTP.sent = []
    send(BRIEF, MAIL, {"INTEL_SMTP_APP_PASSWORD": "pw"}, smtp_factory=FakeSMTP)
    msg = FakeSMTP.sent[0]
    assert msg["Subject"] == BRIEF.subject and msg["X-Intel"] == "daily"
    assert msg.get_content_type() == "multipart/alternative"

def test_send_missing_secret_raises_with_instructions():
    with pytest.raises(RuntimeError, match="INTEL_SMTP_APP_PASSWORD"):
        send(BRIEF, MAIL, {}, smtp_factory=FakeSMTP)

def test_write_dry_run(tmp_path):
    p = write_dry_run(BRIEF, tmp_path, "2026-07-08")
    assert p.read_text().startswith("<p>hi")
    assert (tmp_path / "2026-07-08.txt").exists()

def test_send_uses_verified_tls_and_timeout():
    import ssl
    FakeSMTP.sent = []
    send(BRIEF, MAIL, {"INTEL_SMTP_APP_PASSWORD": "pw"}, smtp_factory=FakeSMTP)
    kw = FakeSMTP.last_kwargs
    assert kw["timeout"] == 30
    assert kw["context"] is not None and kw["context"].check_hostname is True
    assert kw["context"].verify_mode == ssl.CERT_REQUIRED
