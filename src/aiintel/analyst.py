from __future__ import annotations
import json
from pathlib import Path
from aiintel.engines import EngineError, extract_json, get_engine
from aiintel.models import Item

_ACTIONS = {"evaluate", "migrate-candidate", "watch"}

class AnalystError(Exception):
    pass

def build_payload(date_str: str, items: list[Item], item_ids: list[int], stats: dict, profile: dict) -> dict:
    stories = []
    for it, iid in zip(items, item_ids):
        stories.append({
            "id": iid, "title": it.title, "url": it.url_canon or it.url,
            "source": it.source, "trust": it.trust, "score": round(it.score, 1),
            "matched": it.matched, "metrics": it.metrics, "prior_briefings": []})
    return {"date": date_str, "profile": profile, "stories": stories, "stats": stats}

def build_payload_from_stories(date_str: str, stories: list[dict], stats: dict, profile: dict) -> dict:
    return {"date": date_str, "profile": profile, "stories": stories, "stats": stats}

def validate_output(out: dict, valid_ids: set[int], settings: dict,
                    prior_ids: set[int] | None = None) -> dict:
    prior_ids = prior_ids or set()
    if not isinstance(out.get("act"), list) or not isinstance(out.get("signal"), list):
        raise ValueError("act and signal must be lists")
    notes = out.get("materiality_notes") or {}
    act = []
    for a in out["act"]:
        if a.get("story_id") not in valid_ids:
            continue
        if a.get("action") not in _ACTIONS:
            raise ValueError(f"bad action: {a.get('action')!r}")
        if not a.get("headline") or not a.get("why_it_matters"):
            raise ValueError("act item missing headline/why_it_matters")
        a.setdefault("product_refs", [])
        a.setdefault("links", [])
        if not isinstance(a["product_refs"], list) or not isinstance(a["links"], list):
            raise ValueError("product_refs and links must be lists")
        if not a["product_refs"]:
            raise ValueError(f"act {a.get('story_id')} missing product_refs")
        if a["story_id"] in prior_ids and not notes.get(str(a["story_id"])):
            raise ValueError(
                f"act {a['story_id']} re-mentions a story with prior_briefings but has "
                f"no materiality_notes['{a['story_id']}'] — omit it or justify the update")
        act.append(a)
    signal = []
    for s in out["signal"]:
        if s.get("story_id") not in valid_ids or not s.get("line"):
            continue
        if s["story_id"] in prior_ids and not notes.get(str(s["story_id"])):
            raise ValueError(
                f"signal {s['story_id']} re-mentions a story with prior_briefings but has "
                f"no materiality_notes['{s['story_id']}'] — omit it or justify the update")
        signal.append(s)
    if (out["act"] or out["signal"]) and not (act or signal):
        raise ValueError("all story_ids were invalid")
    merges = [m for m in out.get("merges") or []
              if isinstance(m, list) and len(m) == 2 and all(i in valid_ids for i in m)]
    near = out.get("near_miss")
    return {"act": act[: settings["act_max"]],
            "signal": signal[: settings["signal_max"]],
            "merges": merges,
            "materiality_notes": notes,
            "near_miss": near if near in valid_ids else None,
            "fallback": False}

def fallback_brief(payload: dict, settings: dict) -> dict:
    stories = sorted(payload["stories"], key=lambda s: -s["score"])
    return {"act": [],
            "signal": [{"story_id": s["id"], "line": f"{s['title']} ({s['source']})"}
                       for s in stories[: settings["signal_max"]]],
            "merges": [], "materiality_notes": {}, "near_miss": None, "fallback": True}

def run_analyst(payload: dict, engine_name: str, prompts_dir: Path, settings: dict) -> tuple[dict, float]:
    engine = get_engine(engine_name)
    base = (prompts_dir / "analyst.md").read_text(encoding="utf-8")
    base = base.replace("{act_max}", str(settings["act_max"]))
    prompt = base + "\n\n## INPUT\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    valid_ids = {s["id"] for s in payload["stories"]}
    prior_ids = {s["id"] for s in payload["stories"] if s.get("prior_briefings")}
    total_cost, last_err = 0.0, None
    for attempt in range(2):
        try:
            text, cost = engine.run(prompt, timeout=settings["analyst_timeout_seconds"])
            total_cost += cost
            return validate_output(extract_json(text), valid_ids, settings, prior_ids), total_cost
        except (ValueError, EngineError) as e:
            last_err = e
            prompt += f"\n\n## VALIDATION ERROR — fix and resend full JSON\n{e}"
    raise AnalystError(f"analyst failed twice: {last_err}")
