from __future__ import annotations
import html as _html
import sys, time
from datetime import date
from pathlib import Path
from aiintel import analyst as an
from aiintel.collectors import all_collectors
from aiintel.config import load_config, load_secrets
from aiintel.ledger import Ledger
from aiintel.mail import send, write_dry_run
from aiintel.normalize import normalize
from aiintel.render import render
from aiintel.score import score_items

def _state_root(root: Path) -> Path:
    return root

def daily(root: Path, dry_run: bool = False, engine: str | None = None,
          collectors_map: dict | None = None, now: float | None = None) -> int:
    cfg = load_config(root)
    secrets = load_secrets()
    state = _state_root(root)
    date_str = date.today().isoformat()
    engine_name = engine or cfg.settings["engine"]

    global _LAST_STAGE
    raw, errors = [], {}
    _LAST_STAGE = "collect"
    for name, collect in (collectors_map or all_collectors()).items():
        try:
            raw.extend(collect(cfg))
        except Exception as exc:
            errors[name] = str(exc)
            print(f"[collect] {name} failed: {exc}", file=sys.stderr)

    items = normalize(raw)
    with Ledger(state / "ledger.sqlite") as led:
        _LAST_STAGE = "dedupe"
        new, dupes = led.filter_new(items, cfg.settings["dedupe_window_days"],
                                    cfg.settings["fuzzy_threshold"])
        _LAST_STAGE = "score"
        kept, below = score_items(new, cfg.profile, cfg.settings, now=now)
        stats = {"collected": len(items), "suppressed_dupes": dupes,
                 "below_threshold": below, "collector_errors": errors}

        cost = 0.0
        inserted_ids: list[int] = []
        deltas: dict[int, float] = {}
        created_ids: set[int] = set()
        output = {"act": [], "signal": [], "merges": [], "materiality_notes": {},
                  "near_miss": None, "fallback": False}
        stories_by_id: dict = {}
        _LAST_STAGE = "analyst"
        if kept:
            grouped, created_ids = led.attach_stories(kept)
            story_of = {id(it): sid for sid, its in grouped.items() for it in its}
            inserted_ids = led.insert_items(kept, date_str, story_of=story_of)
            deltas = {sid: sum(it.score for it in its) for sid, its in grouped.items()}

        # Everything after the insert is the delivery attempt: if any of it fails,
        # compensate (un-see the run's items and drop ghost stories) so nothing is
        # silently lost — the guard's retry re-briefs them. Delivery is the commit.
        try:
            if kept:
                from aiintel.cluster import stories_payload
                stories, stories_by_id = stories_payload(led, grouped)
                payload = an.build_payload_from_stories(date_str, stories, stats, cfg.profile)
                try:
                    output, cost = an.run_analyst(payload, engine_name, root / "prompts", cfg.settings)
                except an.AnalystError as exc:
                    print(f"[analyst] {exc}", file=sys.stderr)
                    output = an.fallback_brief(payload, cfg.settings)

            _LAST_STAGE = "render"
            brief = render(date_str, output, stories_by_id, stats, cfg.settings)
            _LAST_STAGE = "send"
            if dry_run:
                path = write_dry_run(brief, state / "briefs", date_str)
                print(f"[dry-run] wrote {path}")
            else:
                send(brief, cfg.settings["mail"], secrets)
                print(f"[mail] sent: {brief.subject}")
        except Exception:
            led.compensate_run(inserted_ids, deltas, created_ids)
            raise

        # Delivery succeeded: past this point the one-email contract holds, so a
        # failure must NOT trigger a second FAILED notice (daily_safe checks stage).
        _LAST_STAGE = "finalize"
        # Commit the run's metadata (post-delivery).
        # Resolve merge chains so a briefing under a merged-away id lands on the
        # story that survives, then apply the merges and record what was briefed.
        merges = output.get("merges") or []
        resolved: dict[int, int] = {}
        pairs: list[list[int]] = []
        for keep, dupe in merges:
            keep = resolved.get(keep, keep)
            dupe = resolved.get(dupe, dupe)
            if keep == dupe:
                continue
            pairs.append([keep, dupe])
            resolved[dupe] = keep
            for d in [d for d, k in resolved.items() if k == dupe]:
                resolved[d] = keep
        if pairs:
            led.apply_merges(pairs)
        notes = output.get("materiality_notes") or {}
        # Two merge pairs can both claim the same dupe (e.g. [[A,B],[C,B]]): B
        # resolves to A after the first pair, then A itself becomes a dupe of C
        # in the second. Follow the chain to a fixed point rather than a single
        # hop, so a briefing under any merged-away id — however many hops away
        # from the survivor — never orphans a story_briefings row.
        def _final(sid):
            seen = set()
            while sid in resolved and sid not in seen:
                seen.add(sid); sid = resolved[sid]
            return sid
        entries = [(_final(a["story_id"]), "act", a["headline"],
                    notes.get(str(a["story_id"]), "")) for a in output["act"]]
        entries += [(_final(s["story_id"]), "signal", s["line"],
                     notes.get(str(s["story_id"]), "")) for s in output["signal"]]
        if entries:
            led.mark_briefed(entries, date_str)
        led.record_brief(date_str, "daily", brief.subject, cost, stats)
    return 0

import traceback
import requests
from aiintel.render import Brief

_LAST_STAGE = "start"

def daily_safe(root: Path, dry_run: bool = False, engine: str | None = None,
               collectors_map: dict | None = None) -> int:
    try:
        return daily(root, dry_run=dry_run, engine=engine, collectors_map=collectors_map)
    except Exception:
        tb = "\n".join(traceback.format_exc().splitlines()[-30:])
        date_str = date.today().isoformat()
        subject = f"[intel] FAILED — {_LAST_STAGE}"
        brief = Brief(subject=subject,
                      html=f"<pre>{_html.escape(tb)}</pre>", text=tb)
        state = _state_root(root)
        if _LAST_STAGE == "finalize":
            # Delivery already succeeded — the brief went out. Do not send/write a
            # FAILED notice (one-email contract); just record the failed row below.
            print("[finalize] post-delivery step failed after the brief was delivered; "
                  "suppressing FAILED notice (one-email contract)", file=sys.stderr)
        else:
            try:
                if dry_run:
                    (state / "briefs").mkdir(parents=True, exist_ok=True)
                    (state / "briefs" / f"{date_str}-FAILED.html").write_text(
                        f"<h1>{subject}</h1>{brief.html}", encoding="utf-8")
                else:
                    cfg = load_config(root)
                    send(brief, cfg.settings["mail"], load_secrets())
            except Exception as exc:
                print(f"[failure-mail] could not deliver failure notice: {exc}", file=sys.stderr)
        try:
            with Ledger(state / "ledger.sqlite") as led:
                led.record_brief(date_str, "failed", subject, 0.0, {"stage": _LAST_STAGE})
        except Exception:
            pass
        print(tb, file=sys.stderr)
        return 1

def guard(root: Path) -> int:
    state = _state_root(root)
    with Ledger(state / "ledger.sqlite") as led:
        last = led.last_success()
    if last is None or (time.time() - last) > 26 * 3600:
        print("guard: stale — running daily")
        return daily_safe(root)
    print("guard: fresh")
    return 0

def _head_ok(url: str) -> bool:
    try:
        requests.head(url, timeout=10)
        return True
    except Exception:
        return False

# Cron runs with a minimal PATH; check `claude` resolves under the same PATH the
# install script pins, so doctor catches the cron-class failure C1/I7 guards against.
_CRON_PATH = f"{Path.home()}/.local/bin:/usr/bin:/bin"

def _which_claude() -> bool:
    import shutil
    return shutil.which("claude", path=_CRON_PATH) is not None

def _cron_line_count() -> int:
    import subprocess
    try:
        out = subprocess.run("crontab -l 2>/dev/null | grep -c '# ai-intel'",
                             shell=True, capture_output=True, text=True)
        return int(out.stdout.strip() or 0)
    except Exception:
        return 0

def _secrets_perms_ok() -> bool | None:
    from aiintel.config import SECRETS_PATH
    if not SECRETS_PATH.exists():
        return None  # nothing to check yet
    return (SECRETS_PATH.stat().st_mode & 0o077) == 0

def doctor(root: Path) -> int:
    ok = True
    def check(name, passed, hint=""):
        nonlocal ok
        print(f"{'PASS' if passed else 'FAIL'} {name}{' — ' + hint if (hint and not passed) else ''}")
        ok = ok and passed
    try:
        load_config(root)
        check("config", True)
    except Exception as e:
        check("config", False, str(e))
    check("secrets", bool(load_secrets().get("INTEL_SMTP_APP_PASSWORD")),
          "create ~/.config/ai-intel/secrets.env with INTEL_SMTP_APP_PASSWORD")
    try:
        Ledger(_state_root(root) / "ledger.sqlite").close()
        check("ledger", True)
    except Exception as e:
        check("ledger", False, str(e))
    check("network", _head_ok("https://hn.algolia.com/api/v1/search"), "no route to HN Algolia")
    check("prompt", (root / "prompts/analyst.md").exists(), "prompts/analyst.md missing")
    check("engine", _which_claude(),
          "claude not resolvable on cron PATH — check the PATH line in scripts/install_cron.sh")
    check("cron", _cron_line_count() >= 2, "run scripts/install_cron.sh")
    perms = _secrets_perms_ok()
    if perms is not None:
        check("secrets-perms", perms, "chmod 600 ~/.config/ai-intel/secrets.env")
    return 0 if ok else 1
