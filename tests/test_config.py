from pathlib import Path
from aiintel.config import load_config, load_secrets

ROOT = Path(__file__).resolve().parents[1]

def test_load_config_reads_all_three_files():
    cfg = load_config(ROOT)
    assert cfg.settings["top_k"] == 50
    assert cfg.settings["mail"]["to"] == "you@example.com"
    assert "my-app" in cfg.profile["products"]
    assert any(f["name"] == "simonwillison" for f in cfg.sources["rss"]["feeds"])
    assert "anthropics/claude-code" in cfg.sources["github_releases"]["repos"]

def test_load_secrets_parses_env_format(tmp_path):
    f = tmp_path / "secrets.env"
    f.write_text("INTEL_SMTP_APP_PASSWORD=abcd efgh ijkl mnop\n# comment\n\n")
    assert load_secrets(f)["INTEL_SMTP_APP_PASSWORD"] == "abcd efgh ijkl mnop"

def test_load_secrets_missing_file_is_empty(tmp_path):
    assert load_secrets(tmp_path / "nope.env") == {}
