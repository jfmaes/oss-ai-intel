from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml

SECRETS_PATH = Path("~/.config/ai-intel/secrets.env").expanduser()

@dataclass
class Config:
    root: Path
    settings: dict
    profile: dict
    sources: dict

def _load_yaml(p: Path) -> dict:
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_config(root: Path) -> Config:
    c = root / "config"
    return Config(
        root=root,
        settings=_load_yaml(c / "settings.yaml"),
        profile=_load_yaml(c / "profile.yaml"),
        sources=_load_yaml(c / "sources.yaml"),
    )

def load_secrets(path: Path | None = None) -> dict:
    p = path or SECRETS_PATH
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out
