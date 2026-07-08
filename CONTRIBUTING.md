# Contributing

The two easiest, highest-value contributions are **a new source** and **a new
topic/tag** — both are config-only changes. This doc covers those first, then
the less common cases (a new collector module, a new engine adapter).

## Add a source

There are two ways to add a source, depending on whether it fits the existing
collectors.

### Config-only (the common case)

- **An RSS/Atom feed** → add an entry to `config/sources.yaml` under
  `rss.feeds`:
  ```yaml
  rss:
    feeds:
      - {name: my-source, url: "https://example.com/feed.xml", trust: curated}
  ```
  `trust` is one of `vendor` (the org's own blog/changelog), `curated` (an
  edited newsletter/aggregator), or `community` (forum/social) — it feeds
  directly into the scoring formula (see ARCHITECTURE.md).
- **A GitHub repo** whose releases you want tracked → add its `owner/repo` to
  `config/sources.yaml` under `github_releases.repos`:
  ```yaml
  github_releases:
    repos:
      - my-org/my-repo
  ```

That's it — no code change, no test required, since `rss.py` and
`github_releases.py` already handle arbitrary feeds/repos generically. Open a
PR with just the `config/sources.yaml` diff, or use the
[new source issue template](.github/ISSUE_TEMPLATE/new-source.md) if you'd
rather suggest it than implement it.

### A new collector module (when the source doesn't fit RSS/GitHub/HN)

Some sources need their own polling logic (a different API shape, pagination,
auth-free query params, etc.) — arXiv, Reddit, a sitemap, a changelog JSON
endpoint. That's a new module in `src/aiintel/collectors/`.

**The contract**, followed by all three existing collectors
(`hn.py`, `rss.py`, `github_releases.py`):

```python
def collect(cfg, http_get=None) -> list[Item]:
    """cfg is the loaded Config (cfg.settings, cfg.sources, cfg.profile).
    http_get defaults to requests.get; tests inject a fake to avoid real
    network calls. Must never raise — isolate your own failures."""
```

A minimal example, `src/aiintel/collectors/example.py`:

```python
from __future__ import annotations
import sys, time
import requests
from aiintel.models import Item

def collect(cfg, http_get=None) -> list[Item]:
    get = http_get or requests.get
    cutoff = time.time() - cfg.settings["lookback_hours"] * 3600
    items = []
    try:
        resp = get("https://example.com/api/latest", timeout=30)
        resp.raise_for_status()
        for entry in resp.json().get("entries", []):
            ts = float(entry["published_ts"])
            if ts < cutoff:
                continue
            items.append(Item(
                url=entry["url"], title=entry["title"],
                source="example", trust="community",
                published=ts, metrics={}))
    except Exception as exc:
        print(f"[example] failed: {exc}", file=sys.stderr)
    return items
```

Rules that matter (mirrored in every existing collector):

1. **Never raise.** Wrap your fetch(es) in `try/except Exception`, print
   `[your-source] ... failed: <exc>` to stderr, and return whatever you
   already have. One dead source must never take down a run. If your
   collector polls *several* endpoints (like `rss.py` iterating feeds, or
   `github_releases.py` iterating repos), isolate each one individually —
   one bad feed shouldn't drop the others.
2. **Accept `http_get`** and use it instead of calling `requests.get`
   directly — that's what makes the collector testable without hitting the
   network.
3. **Respect `cfg.settings["lookback_hours"]`** — drop anything older than
   the cutoff.
4. **Pick a `source` prefix convention** — `hn`, `rss:<name>`,
   `gh:<owner>/<repo>` are the existing ones; scoring's pinned-repo credit
   specifically checks for a `gh:` prefix, so keep that one if your source is
   GitHub-shaped.
5. **`trust`** is one of `vendor` / `curated` / `community` (see above).

Then:

- **Register it** in `src/aiintel/collectors/__init__.py`:
  ```python
  from aiintel.collectors import hn, rss, github_releases, example

  def all_collectors() -> dict:
      return {"hn": hn.collect, "rss": rss.collect,
              "github_releases": github_releases.collect,
              "example": example.collect}
  ```
- **Add a test** — `tests/test_collector_example.py`, following the pattern
  in `tests/test_collector_rss.py` or `tests/test_collector_hn.py`: build a
  fake `http_get` that returns canned responses, assert on the `Item` fields
  you produce, and assert that a failure is isolated (printed, not raised).

## Add a topic/tag

Edit `config/profile.yaml`. Two sections:

- **`products`** — things you build; a match is a strong signal.
- **`domains`** — themes you track generally (models, agents, security,
  tooling, ...).

Each entry is a `topics` list and a `weight` (`high` / `med` / `low`, worth 3
/ 2 / 1 points per match — see ARCHITECTURE.md's scoring formula). A topic
phrase matches when **every word in the phrase** appears as a whole word in
the item's title — `rag` matches "the new RAG pipeline" but not "storage" or
"fragment". This is entirely config; no code change needed, and nothing else
in the codebase references these keys by name.

## Add an engine

The analyst call is behind a small adapter seam
(`src/aiintel/engines/`) — see ARCHITECTURE.md for the full contract. A new
engine is one module with one function:

```python
# src/aiintel/engines/my_engine.py
def run(prompt: str, timeout: int = 300) -> tuple[str, float]:
    """Return (raw_text_response, cost_usd). Raise EngineError (from
    aiintel.engines) on any engine-level failure: crash, timeout, missing
    binary, malformed response envelope."""
```

Register it in `src/aiintel/engines/__init__.py`'s `_ENGINES` dict, add a
test following `tests/test_engines.py`'s pattern for the `claude` engine
(monkeypatch the subprocess/HTTP call, assert both the happy path and each
failure mode raise `EngineError`), and it's selectable via
`config/settings.yaml`'s `engine:` key or `--engine` on the CLI.

## Running tests

```bash
uv run pytest -q          # whole suite, quiet
uv run pytest -v          # verbose
uv run pytest tests/test_score.py -v   # one file
```

All tests use temp dirs/paths and injected fakes (`tmp_path`, `monkeypatch`,
fake `http_get`/engine functions) — nothing hits the network or sends real
mail.

## The `Item` contract

`src/aiintel/models.py`:

```python
@dataclass
class Item:
    url: str
    title: str
    source: str        # "hn" | "rss:<name>" | "gh:<owner>/<repo>"
    trust: str         # "vendor" | "curated" | "community"
    published: float   # unix timestamp
    metrics: dict       # source-specific extras, e.g. {"points": 120} for HN
    # everything below is filled in later by the pipeline — collectors
    # should leave these at their defaults:
    url_canon: str = ""
    title_norm: str = ""
    natural_key: str = ""
    score: float = 0.0
    matched: list[str] = field(default_factory=list)
```

A collector only ever populates the first six fields. `normalize.py` fills
`url_canon` / `title_norm` / `natural_key`; `score.py` fills `score` /
`matched`. Setting those yourself in a collector is harmless (they get
overwritten) but not meaningful.

## PR checklist

- [ ] `uv run pytest -q` passes
- [ ] No secrets, API keys, tokens, or personal contact info anywhere in the diff
- [ ] A new/changed source is public and free — no paid plan or auth token required to poll it
- [ ] A new collector follows the contract above (never raises, accepts `http_get`, respects `lookback_hours`) and ships with a test
- [ ] A new collector is registered in `all_collectors()`
- [ ] Docs updated if behavior changed (README.md / ARCHITECTURE.md)

That's it — a source or topic PR should be a five-to-ten-minute round trip.
