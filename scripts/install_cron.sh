#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
LOCK="$ROOT/.run.lock"
TAG="# ai-intel"
# PATH line must be FIRST so cron resolves `claude` (invoked bare by the engine)
# and `flock`; flock -n serialises runs so a slow daily never overlaps the guard.
# The PATH line itself is emitted WITHOUT the tag: per crontab(5), environment
# lines don't support trailing comments, so "... # ai-intel" would be parsed as
# literal PATH text, corrupting the last component. Idempotency is instead kept
# by stripping any prior PATH=... line explicitly below.
( crontab -l 2>/dev/null | grep -v "$TAG" | grep -v "^PATH=$HOME/.local/bin" || true
  echo "PATH=$HOME/.local/bin:/usr/bin:/bin"
  echo "15 6 * * * flock -n $LOCK -c \"cd $ROOT && $UV run ai-intel run daily >> $ROOT/cron.log 2>&1\" $TAG"
  echo "5 * * * * flock -n $LOCK -c \"cd $ROOT && $UV run ai-intel guard >> $ROOT/cron.log 2>&1\" $TAG"
) | crontab -
echo "installed:"
crontab -l | grep "$TAG"
