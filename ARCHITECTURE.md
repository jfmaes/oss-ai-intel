# Architecture

This document describes how a run works, why it's structured this way, and
the contracts a contributor needs to respect. The code is the source of
truth; this is the map.

## Pipeline, end to end

```
collectors (hn, rss, github_releases)
        │  list[Item], raw
        ▼
normalize            canonical URL, normalized title, natural_key (arxiv id / gh repo)
        │
        ▼
Ledger.filter_new    Layer 1 — link dedupe (see below)
        │  list[Item], new only
        ▼
score_items          profile-weighted relevance score, quiet-threshold cut, top_k cap
        │  list[Item], kept only
        ▼
Ledger.attach_stories  Layer 2 — story clustering + materiality gate (see below)
        │  dict[story_id, list[Item]]
        ▼
stories_payload      one row per story: best title/url, corroboration count,
        │             prior_briefings so far
        ▼
run_analyst          ONE LLM call → {act[], signal[], merges[], materiality_notes{}, near_miss}
        │             (engine-adapter seam — see below)
        ▼
render               subject + HTML + text brief
        ▼
mail.send  (or write_dry_run)
```

Everything up to and including `attach_stories`/`insert_items` is cheap,
deterministic, local code. Exactly one LLM call happens per run, right before
rendering. That call decides *what a human should see*; it never decides
*what was collected*.

## The 3-layer no-repetition memory

The differentiator of this pipeline isn't collection — RSS/HN/GitHub polling
is easy. It's never showing you the same thing twice, at three different
altitudes.

### Layer 1 — Link ledger (item level)

`Ledger.filter_new` (`src/aiintel/ledger.py`) checks every newly collected
item against the `items` table:

- an exact `url_canon` match (after `normalize.py` strips tracking params,
  lowercases the host, drops `www.`, etc.) is always a dupe;
- a fuzzy title match — `rapidfuzz.fuzz.token_set_ratio` against every item
  title seen within `dedupe_window_days` — is a dupe once the ratio clears
  `fuzzy_threshold`.

This catches "the same link" and "the same headline reworded by a different
outlet" before anything reaches scoring. It has no concept of what the link
is *about* — that's Layer 2.

### Layer 2 — Stories + materiality gate (event level)

Items that survive Layer 1 get grouped into **stories**
(`Ledger.attach_stories`): the same `natural_key` (an arXiv id or a
`github.com/<owner>/<repo>`, extracted in `normalize.py`) always joins the
same story; otherwise a fuzzy title match against stories seen in the last 14
days joins it; otherwise a new story is created.

Every story carries its briefing history (`story_briefings`, exposed as
`prior_briefings` in the analyst payload). The analyst prompt
(`prompts/analyst.md`) enforces the gate: an ACT or SIGNAL item that
references a story with non-empty `prior_briefings` is **rejected** unless
the model supplies a `materiality_notes` entry justifying *why this is a
material update* (a confirmed breaking change, independent reproduction,
major adoption, security impact). `analyst.validate_output` enforces this
mechanically — a re-mention without a justification raises, forcing a retry.
The renderer prefixes a justified re-mention with `UPDATE:`.

This is "the same underlying event is briefed once, then only on material
deltas" — the gate that stops a story from being re-told every day it keeps
trending.

### Layer 3 — Topic dossiers (theme level) — extension point

The design calls for a third altitude: long-running, per-topic state (a
"state of play" for `rag`, `agents`, etc.) that periodically re-synthesizes
everything briefed under that topic into a standing summary, so a slow-moving
trend doesn't have to be re-derived from scratch every time it comes up. The
`dossiers/` path is reserved (gitignored, since it's per-instance accumulated
state) for exactly this.

**This layer isn't implemented in this OSS cut** — only Layers 1 and 2 ship.
It's one of the more interesting things to pick up; see
[CONTRIBUTING.md](CONTRIBUTING.md) if you want to take a swing at it.

## Scoring formula

`score_items` (`src/aiintel/score.py`) runs after Layer 1, before Layer 2,
and decides what's even worth clustering into a story:

```
topic_points = Σ weight_points(group)  for every products/domains group
                                       whose topic phrase whole-word-matches
                                       the normalized title
               weight_points: high=3, med=2, low=1

# a pinned GitHub repo release with zero topic hits still reads as explicit
# interest (you chose to watch that repo) — floor of 1 point
if topic_points == 0 and source starts with "gh:": topic_points = 1

trust_multiplier:  vendor=1.5, curated=1.2, community=1.0

velocity:
  hn items:    min(log1p(points / age_hours * 24), 3.0)
  everything else: max(0.3, 1.5 - age_hours / 48)

score = (0.5 + min(topic_points, 6)) * trust_multiplier * (0.5 + velocity)
```

Items scoring below `quiet_score_threshold` never reach the analyst. Of the
rest, only the top `top_k` (by score) are sent. `matched` (which
products/domains groups fired) rides along in the analyst payload so the
model — and you, reading `prompts/analyst.md`'s requirement that every ACT
item name a `product_refs` entry — always knows *why* something scored.

A topic phrase match requires **every word** in the phrase to appear as a
whole word in the title (`_topic_hits` in `score.py`) — "rag" matches "RAG
pipeline" but not "storage", "drops", or "fragment".

## Engine-adapter seam

`src/aiintel/engines/__init__.py` is a tiny registry:

```python
_ENGINES = {"claude": "aiintel.engines.claude"}

def get_engine(name: str):
    ...  # imports the module, returns it

def extract_json(text: str) -> dict: ...  # pulls the JSON object out of free-form model output
```

An engine module needs exactly one function:

```python
def run(prompt: str, timeout: int = 300) -> tuple[str, float]:
    """Return (raw_text_response, cost_usd). Raise EngineError on any
    engine-level failure (crash, timeout, missing binary, bad envelope)."""
```

`analyst.run_analyst` calls `engine.run`, validates the JSON against the
contract (`analyst.validate_output`), and on a validation failure appends the
error to the prompt and retries **once** before giving up and falling back to
`analyst.fallback_brief` (a deterministic top-N-by-score SIGNAL list, so a
broken analyst degrades the brief instead of losing the run).

Only the `claude` engine ships (shells out to the `claude` CLI with
`--output-format json`, reads `total_cost_usd` off the envelope). Adding
`codex` or `openrouter` means writing one new module with that one function —
see [CONTRIBUTING.md](CONTRIBUTING.md#add-an-engine).

## The one-email-per-run failure contract

`run.daily_safe` wraps the entire pipeline. Every scheduled invocation
resolves to **exactly one** outbound email:

1. the rendered brief (`[intel] <date> — N ACT · M SIGNAL`),
2. `[intel] <date> — all quiet` if nothing cleared the bar, or
3. `[intel] FAILED — <stage>` with the last 30 lines of the traceback, if
   anything raised.

**Delivery is the commit point.** New items are inserted into the ledger and
stories are attached/updated *before* the analyst call and delivery attempt,
because the analyst payload needs stable ids to reference. But if anything
from that point on fails — the analyst, rendering, or the send itself — the
run is compensated: `Ledger.compensate_run` deletes the just-inserted items,
rolls back the score deltas it added to any story's `cum_score`, and drops
any story that was created this run and ended up with zero items. The
guard's hourly retry then genuinely re-collects and re-briefs the same
items — nothing is silently marked "seen" unless the email actually went out.

One asymmetry is deliberate: once delivery succeeds, the run enters a
`finalize` stage (recording merges, marking stories briefed, writing
`brief_log`). If *that* bookkeeping fails, `daily_safe` does **not** send a
second `FAILED` email — the brief already reached you, and a second email for
a post-delivery bookkeeping error would violate the one-email contract. It
logs to stderr and records a `failed` row instead.

`ai-intel guard` is the retry path: it checks `last_success()` in the ledger
and re-runs `daily_safe` if the last non-failed run is more than 26 hours
old — the hourly cron job that catches a missed or failed morning run.

## Data model (`ledger.sqlite`)

- **`items`** — every item ever inserted: canonical URL, normalized title,
  source, trust, natural key, timestamps, which story it belongs to. Backs
  Layer 1.
- **`stories`** — clustered events: natural key, title, status
  (`new`/`developing`), cumulative score, last-briefed date, brief count.
  Backs Layer 2.
- **`story_briefings`** — one row per thing ever said about a story (section,
  line, materiality note). This is what `prior_briefings` is built from.
- **`brief_log`** — one row per run outcome (kind, subject, cost, stats) —
  what `guard`'s staleness check and `doctor` read.

## Module map

```
src/aiintel/
  models.py        Item dataclass — the contract every collector must produce
  normalize.py      canonical_url / natural_key / norm_title
  collectors/       hn.py, rss.py, github_releases.py — all collect(cfg, http_get=None) -> list[Item]
  ledger.py         Layers 1 & 2, sqlite-backed
  score.py          profile-weighted scoring
  cluster.py        turns grouped stories into the analyst's story payload rows
  analyst.py        builds the LLM payload, validates/repairs its output, fallback brief
  engines/          the engine-adapter seam (claude.py ships)
  render.py         brief → (subject, html, text), with output escaping
  mail.py           SMTP send + dry-run file writer
  run.py            daily() / daily_safe() / guard() / doctor() — orchestration + the failure contract
  config.py         loads config/*.yaml + ~/.config/ai-intel/secrets.env
```
