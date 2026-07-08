from aiintel.render import render

STORIES = {11: {"id": 11, "title": "Big Thing", "url": "https://s.com", "source": "hn"},
           12: {"id": 12, "title": "Small Thing", "url": "https://t.com", "source": "rss:openai"},
           13: {"id": 13, "title": "Near Miss Thing", "url": "https://u.com", "source": "hn"}}
STATS = {"collected": 40, "suppressed_dupes": 10, "below_threshold": 5}
SETTINGS = {}

def _out(act=(), signal=(), fallback=False, near=None):
    return {"act": list(act), "signal": list(signal), "merges": [],
            "materiality_notes": {}, "near_miss": near, "fallback": fallback}

ACT = {"story_id": 11, "headline": "Big Thing shipped", "why_it_matters": "Affects my-rag-app's reranker.",
       "product_refs": ["my-rag-app"], "action": "evaluate", "links": ["https://s.com"]}
SIG = {"story_id": 12, "line": "OpenAI posted a small thing."}

def test_normal_subject_and_sections():
    b = render("2026-07-08", _out([ACT], [SIG], near=13), STORIES, STATS, SETTINGS)
    assert b.subject == "[intel] 2026-07-08 — 1 ACT · 1 SIGNAL"
    for frag in ["Big Thing shipped", "evaluate", "my-rag-app", "OpenAI posted", "Near Miss Thing", "40 collected"]:
        assert frag in b.html and frag in b.text

def test_quiet_subject():
    b = render("2026-07-08", _out(), STORIES, STATS, SETTINGS)
    assert b.subject == "[intel] 2026-07-08 — all quiet"
    assert "40 collected" in b.text

def test_fallback_banner():
    b = render("2026-07-08", _out(signal=[SIG], fallback=True), STORIES, STATS, SETTINGS)
    assert "analyst offline" in b.subject and "analyst failed" in b.html.lower()

def test_injection_hardening():
    stories = {9: {"id": 9, "title": "Evil <img src=x onerror=alert(1)>", "url": "javascript:alert(1)", "source": "hn"}}
    out = {"act": [{"story_id": 9, "headline": "x<script>y</script>", "why_it_matters": "w",
                    "product_refs": ["<b>p</b>"], "action": "watch",
                    "links": ["javascript:alert(1)", "https://ok.com/a"]}],
           "signal": [{"story_id": 9, "line": "line <script>z</script>"}],
           "merges": [], "materiality_notes": {}, "near_miss": 9, "fallback": False}
    b = render("2026-07-08", out, stories, {"collected": 1, "suppressed_dupes": 0, "below_threshold": 0}, {})
    assert "<script>" not in b.html and "javascript:" not in b.html
    assert "https://ok.com/a" in b.html
    assert "onerror" not in b.html or "&lt;img" in b.html  # escaped title in near-miss footer
