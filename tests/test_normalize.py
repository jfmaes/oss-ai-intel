from aiintel.models import Item
from aiintel.normalize import canonical_url, natural_key, norm_title, normalize

def _item(url, title="T"):
    return Item(url=url, title=title, source="hn", trust="community", published=0.0, metrics={})

def test_canonical_url_strips_tracking_and_fragment():
    u = "https://Example.com/Post/?utm_source=x&utm_campaign=y&ref=hn&id=7#frag"
    assert canonical_url(u) == "https://example.com/Post?id=7"

def test_canonical_url_github_repo_normalized():
    assert canonical_url("https://www.github.com/LangChain-AI/langgraph/") == "https://github.com/langchain-ai/langgraph"

def test_natural_key_github_repo_from_deep_link():
    assert natural_key("https://github.com/langchain-ai/langgraph/releases/tag/v1.0", "x") == "gh:langchain-ai/langgraph"

def test_natural_key_arxiv():
    assert natural_key("https://arxiv.org/abs/2507.01234v2", "x") == "arxiv:2507.01234"
    assert natural_key("https://arxiv.org/pdf/2507.01234", "x") == "arxiv:2507.01234"

def test_natural_key_none():
    assert natural_key("https://example.com/blog", "x") == ""

def test_norm_title_lowercases_and_collapses():
    assert norm_title("  Show HN:  LangGraph 2.0 — now faster!  ") == "show hn: langgraph 2.0 — now faster!"

def test_normalize_fills_fields_and_drops_empty():
    items = normalize([_item("https://github.com/org/repo/issues/5", "Hi"), _item("", "empty")])
    assert len(items) == 1
    assert items[0].url_canon == "https://github.com/org/repo/issues/5"
    assert items[0].natural_key == "gh:org/repo"
    assert items[0].title_norm == "hi"

def test_natural_key_github_reserved_paths_excluded():
    assert natural_key("https://github.com/orgs/openai/discussions/1", "x") == ""
    assert natural_key("https://github.com/topics/rag", "x") == ""

def test_natural_key_arxiv_requires_arxiv_host():
    assert natural_key("https://web.archive.org/web/2024/https://arxiv.org/abs/2507.01234", "x") == ""

def test_natural_key_arxiv_subdomain_ok():
    assert natural_key("https://export.arxiv.org/abs/2507.01234", "x") == "arxiv:2507.01234"
