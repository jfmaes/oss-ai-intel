import time
from aiintel.models import Item
from aiintel.score import score_items

PROFILE = {
    "products": {"my-rag-app": {"topics": ["rag", "reranker"], "weight": "high"}},
    "domains": {"founder-stack": {"topics": ["claude"], "weight": "med"}},
}
SETTINGS = {"top_k": 50, "quiet_score_threshold": 3.0}

def _item(title, source="hn", trust="community", points=0, age_h=4.0):
    return Item(url="u", title=title, source=source, trust=trust,
                published=time.time() - age_h * 3600, metrics={"points": points},
                url_canon="u", title_norm=title.lower())

def test_topic_match_whole_word_only():
    kept, _ = score_items([_item("Cloud storage pricing drops")], PROFILE, SETTINGS)
    assert kept == []  # "storage" must not match topic "rag"

def test_matched_product_scores_and_names():
    kept, _ = score_items([_item("A new reranker beats cross-encoders", trust="curated", points=120)], PROFILE, SETTINGS)
    assert len(kept) == 1
    assert kept[0].matched == ["my-rag-app"]
    assert kept[0].score > 3.0

def test_sorted_desc_and_suppressed_count():
    a = _item("New reranker architecture", points=300)
    b = _item("claude gets minor update", trust="community", points=0, age_h=30)
    c = _item("Gardening tips for summer")
    kept, suppressed = score_items([a, b, c], PROFILE, SETTINGS)
    assert [i.title for i in kept][0] == a.title
    assert suppressed >= 1

def test_pinned_gh_source_zero_match_clears_threshold():
    # I5: a pinned repo (gh:) release with no topic hit still reads as explicit
    # interest — a floor of 1 pt lets a fresh release clear the quiet threshold.
    it = _item("An unrelated repository maintenance release", source="gh:org/repo",
               trust="vendor", age_h=4.0)
    kept, _ = score_items([it], PROFILE, SETTINGS)
    assert len(kept) == 1
    assert it.matched == []          # the credit is not a topic match
    assert it.score >= 3.0

def test_pinned_credit_only_for_gh_sources():
    # the credit is pinned-source only: a non-gh zero-match item stays suppressed.
    it = _item("An unrelated maintenance note", source="hn", trust="vendor", age_h=4.0)
    kept, _ = score_items([it], PROFILE, SETTINGS)
    assert kept == []
