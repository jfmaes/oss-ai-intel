from __future__ import annotations
import html as h
from dataclasses import dataclass

@dataclass
class Brief:
    subject: str
    html: str
    text: str

def _safe_url(url: str) -> str:
    return url if url.startswith(("http://", "https://")) else ""

def _footer(stats: dict, near_title: str | None) -> tuple[str, str]:
    suppressed = stats.get("suppressed_dupes", 0) + stats.get("below_threshold", 0)
    line = (f"{stats.get('collected', 0)} collected · {suppressed} suppressed "
            f"({stats.get('suppressed_dupes', 0)} dupes, {stats.get('below_threshold', 0)} low relevance)")
    if near_title:
        line += f" · Top near-miss: {near_title}"
    return (f'<p style="color:#888;font-size:12px;margin-top:24px">{h.escape(line)}</p>', line)

def render(date_str: str, output: dict, stories_by_id: dict, stats: dict, settings: dict) -> Brief:
    act, signal = output["act"], output["signal"]
    quiet = not act and not signal
    if quiet:
        subject = f"[intel] {date_str} — all quiet"
    else:
        subject = f"[intel] {date_str} — {len(act)} ACT · {len(signal)} SIGNAL"
    if output.get("fallback"):
        subject += " · ⚠ analyst offline"

    parts_h, parts_t = [], []
    if output.get("fallback"):
        parts_h.append('<p style="color:#b00">⚠ The analyst failed; below is the raw heuristic ranking.</p>')
        parts_t.append("⚠ The analyst failed; below is the raw heuristic ranking.")
    if quiet:
        parts_h.append("<p>Nothing actionable today.</p>")
        parts_t.append("Nothing actionable today.")
    if act:
        parts_h.append('<h2 style="font-size:16px">ACT</h2>')
        parts_t.append("== ACT ==")
        for a in act:
            s = stories_by_id.get(a["story_id"], {})
            headline = a["headline"]
            if s.get("prior_briefings"):
                headline = f"UPDATE: {headline}"
            safe_links = [u for u in (a["links"] or [s.get("url", "")]) if _safe_url(u)]
            links = " · ".join(f'<a href="{h.escape(u)}">{h.escape(u)}</a>' for u in safe_links)
            refs = ", ".join(a["product_refs"])
            parts_h.append(
                f'<div style="margin:12px 0;padding:10px;border-left:3px solid #c40">'
                f'<b>{h.escape(headline)}</b> <span style="color:#c40">[{h.escape(a["action"])}]</span><br>'
                f'{h.escape(a["why_it_matters"])}<br>'
                f'<i>{h.escape(refs)}</i><br>{links}</div>')
            parts_t.append(f'* {headline} [{a["action"]}] — {a["why_it_matters"]} ({refs}) '
                           + " ".join(safe_links))
    if signal:
        parts_h.append('<h2 style="font-size:16px">SIGNAL</h2><ul>')
        parts_t.append("== SIGNAL ==")
        for sg in signal:
            s = stories_by_id.get(sg["story_id"], {})
            line = sg["line"]
            if s.get("prior_briefings"):
                line = f"UPDATE: {line}"
            url = _safe_url(s.get("url", ""))
            parts_h.append(f'<li>{h.escape(line)} <a href="{h.escape(url)}">link</a></li>')
            parts_t.append(f'- {line} {url}')
        parts_h.append("</ul>")

    near = output.get("near_miss")
    near_title = stories_by_id.get(near, {}).get("title") if near else None
    fh, ft = _footer(stats, near_title)
    body_html = (f'<div style="font-family:sans-serif;max-width:640px;margin:auto">'
                 f'<h1 style="font-size:18px">AI Intel — {h.escape(date_str)}</h1>'
                 + "".join(parts_h) + fh + "</div>")
    body_text = f"AI Intel — {date_str}\n\n" + "\n".join(parts_t) + f"\n\n{ft}\n"
    return Brief(subject=subject, html=body_html, text=body_text)
