from __future__ import annotations
import json, subprocess
from aiintel.engines import EngineError

def run(prompt: str, timeout: int = 300) -> tuple[str, float]:
    try:
        proc = subprocess.run(
            ["claude", "-p", "--output-format", "json"],
            input=prompt, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise EngineError(f"claude -p exit {proc.returncode}: {proc.stderr[-500:]}")
        env = json.loads(proc.stdout)
        if env.get("is_error"):
            raise EngineError(f"claude -p error result: {str(env.get('result'))[:500]}")
        return env.get("result") or "", float(env.get("total_cost_usd") or 0.0)
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError,
            json.JSONDecodeError) as exc:
        raise EngineError(f"claude engine: {exc}") from exc
