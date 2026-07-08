from __future__ import annotations
import importlib, json, re

class EngineError(Exception):
    """Any engine-level failure: crash, timeout, missing binary, bad envelope."""

_ENGINES = {"claude": "aiintel.engines.claude"}

def get_engine(name: str):
    if name not in _ENGINES:
        raise ValueError(f"unknown engine: {name} (have: {', '.join(_ENGINES)})")
    return importlib.import_module(_ENGINES[name])

def extract_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [m.group(1)] if m else []
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON object found in engine output")
