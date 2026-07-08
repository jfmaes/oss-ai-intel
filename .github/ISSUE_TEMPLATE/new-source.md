---
name: New source
about: Suggest an RSS feed, GitHub repo, or collector for the AI-news pipeline
title: "[source] "
labels: new-source
---

**What is it?**
Name and URL of the feed / repo / API you're proposing.

**What kind of source?**
- [ ] RSS/Atom feed → add to `config/sources.yaml` under `rss.feeds`
- [ ] GitHub repo to watch releases → add to `config/sources.yaml` under `github_releases.repos`
- [ ] Something else (needs a new collector — see CONTRIBUTING.md "Add a source")

**Why is it worth including?**
One or two sentences: what makes this a good signal source for an AI-news brief
(vendor blog, high-signal community, active release cadence, etc.)?

**Is it public and free to poll?**
- [ ] Yes — no auth, no paid API key required
- [ ] No / unsure (explain below)

**Have you verified the feed/endpoint works?**
Paste the command you used to check it, e.g.:
```
curl -s <url> | head -c 500
```
