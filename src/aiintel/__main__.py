from __future__ import annotations
import argparse, os, sys
from pathlib import Path
from aiintel import run as runmod

def main() -> None:
    root = Path(os.environ.get("AI_INTEL_ROOT", Path.home() / "projects/ai-intel"))
    ap = argparse.ArgumentParser(prog="ai-intel")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("kind", choices=["daily"])
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--engine")
    sub.add_parser("guard")
    sub.add_parser("doctor")
    args = ap.parse_args()
    if args.cmd == "run" and args.kind == "daily":
        sys.exit(runmod.daily_safe(root, dry_run=args.dry_run, engine=args.engine))
    elif args.cmd == "guard":
        sys.exit(runmod.guard(root))
    elif args.cmd == "doctor":
        sys.exit(runmod.doctor(root))

if __name__ == "__main__":
    main()
