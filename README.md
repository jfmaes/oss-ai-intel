# ai-intel

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)

A personal AI-landscape intelligence pipeline you configure with your own stack:
**collectors → dedupe → profile-scored ranking → one LLM analyst call → email
brief** — with a 3-layer no-repetition memory so you never see the same thing
twice.

Point it at the feeds, repos, and topics you actually care about, run it on a
schedule, and get a short daily email: a handful of things that might change
what you're doing (**ACT**), a few worth knowing (**SIGNAL**), or nothing at
all if nothing happened. It never re-tells you about the same link, and it
only re-mentions a running story when something material changed.

The engine that talks to an LLM is a small adapter seam — the pipeline itself
doesn't care which model does the analysis. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Why

Most "AI news" is the same handful of launches reblogged everywhere. This
pipeline is built around a different premise: define *your* stack once (your
products, the domains you track), let cheap deterministic code do collection
and filtering, and spend exactly one LLM call per run deciding what's actually
worth your attention — never more than once per story.

## Quick start

```bash
# 1. Install dependencies
uv sync

# 2. Configure it for you (see below) — or just start with the committed
#    defaults, which already point at a solid set of public AI-news sources.
$EDITOR config/profile.yaml    # your products/topics
$EDITOR config/sources.yaml    # your feeds/repos

# 3. Add secrets (Gmail app password — Google Account → Security →
#    2-Step Verification → App passwords)
mkdir -p ~/.config/ai-intel
echo 'INTEL_SMTP_APP_PASSWORD=xxxx xxxx xxxx xxxx' > ~/.config/ai-intel/secrets.env
chmod 600 ~/.config/ai-intel/secrets.env

# 4. Sanity check — everything must PASS
uv run ai-intel doctor

# 5. Do a dry run (writes to briefs/, sends no mail)
uv run ai-intel run daily --dry-run

# 6. When you're happy, send it for real
uv run ai-intel run daily
```

Also update `config/settings.yaml`'s `mail.to` / `mail.from` to your own
address — it ships with a placeholder.

### Running it on a schedule

`./scripts/install_cron.sh` installs two cron entries: a daily run and an
hourly "guard" that catches up if the last successful run is more than 26
hours old (so a missed morning doesn't mean a missed day). Requires a working
system cron daemon. Tail `cron.log` (gitignored) to watch it run.

## Configure it for you

This repo ships with generic, working defaults — it's meant to be forked and
tuned, not used as-is forever.

- **`config/profile.yaml`** — your topic taxonomy. `products` are the things
  *you* build (a match here is a strong "this might affect my roadmap"
  signal); `domains` are themes you track more generally (models, agents,
  security, tooling, ...). This is the main dial: add your own products,
  rename domains, adjust `weight`. See [ARCHITECTURE.md](ARCHITECTURE.md) for
  exactly how these topics turn into a score.
- **`config/sources.yaml`** — your feeds and repos: RSS/Atom feeds, GitHub
  repos to watch for releases, and Hacker News search thresholds. The
  committed defaults are a solid public AI/ML news diet (OpenAI, DeepMind,
  Hugging Face, Simon Willison, smol.ai, Latent Space, lobste.rs, plus a
  curated list of agent/RAG/inference repos) — add your own.
- **`config/settings.yaml`** — the tunables: how many ACT/SIGNAL items per
  brief, the collector lookback window, dedupe thresholds, which engine runs
  the analyst, and mail delivery settings.

## Engines

The analyst call goes through a small adapter seam (`src/aiintel/engines/`).
The `claude` engine ships today (shells out to the `claude` CLI). Adding a
`codex` or `openrouter` adapter is a same-shape, self-contained change — see
[CONTRIBUTING.md](CONTRIBUTING.md#add-an-engine).

## The one-email-per-run contract

Every scheduled run sends **exactly one** email: the brief, "all quiet", or
`[intel] FAILED — <stage>`. The same link is never surfaced twice; the same
underlying story is only re-mentioned on a material update (prefixed
`UPDATE:`). Delivery is the commit point — if anything fails before the brief
goes out, the run's items are un-seen and any ghost story it created is
dropped, so nothing is silently lost and the hourly guard genuinely re-briefs
them on the next successful run. Full details in
[ARCHITECTURE.md](ARCHITECTURE.md).

## Contributing

Adding a source (a feed, a repo) or a topic is meant to be a ten-minute PR —
see [CONTRIBUTING.md](CONTRIBUTING.md). Adding a whole new collector or engine
adapter is a bit more work but follows a documented contract with a test to
copy from. Bug reports, doc fixes, and "here's a source you should track"
issues are all welcome — see the
[new source issue template](.github/ISSUE_TEMPLATE/new-source.md).

## Tests

```bash
uv run pytest -q
```

## License

MIT — see [LICENSE](LICENSE).
