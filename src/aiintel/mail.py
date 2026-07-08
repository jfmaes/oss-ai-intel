from __future__ import annotations
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from aiintel.render import Brief

def send(brief: Brief, mail_cfg: dict, secrets: dict, smtp_factory=None) -> None:
    pw = secrets.get("INTEL_SMTP_APP_PASSWORD")
    if not pw:
        raise RuntimeError(
            "missing INTEL_SMTP_APP_PASSWORD — create a Gmail app password "
            "(Google Account → Security → 2-Step Verification → App passwords) and put "
            "INTEL_SMTP_APP_PASSWORD=<value> in ~/.config/ai-intel/secrets.env (chmod 600)")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = brief.subject, mail_cfg["from"], mail_cfg["to"]
    msg["X-Intel"] = "daily"
    msg.set_content(brief.text)
    msg.add_alternative(brief.html, subtype="html")
    factory = smtp_factory or smtplib.SMTP_SSL
    with factory(mail_cfg["smtp_host"], mail_cfg["smtp_port"],
                 timeout=30, context=ssl.create_default_context()) as s:
        s.login(mail_cfg["from"], pw)
        s.send_message(msg)

def write_dry_run(brief: Brief, briefs_dir: Path, date_str: str) -> Path:
    briefs_dir.mkdir(parents=True, exist_ok=True)
    html_path = briefs_dir / f"{date_str}.html"
    html_path.write_text(brief.html, encoding="utf-8")
    (briefs_dir / f"{date_str}.txt").write_text(f"{brief.subject}\n\n{brief.text}", encoding="utf-8")
    return html_path
