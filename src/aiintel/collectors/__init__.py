from aiintel.collectors import hn, rss, github_releases  # noqa: E402

def all_collectors() -> dict:
    return {"hn": hn.collect, "rss": rss.collect, "github_releases": github_releases.collect}
