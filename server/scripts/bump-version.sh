#!/usr/bin/env bash
# Bump repo root VERSION with a new UTC build suffix so every deploy has a unique badge.
# Format: <base>+<YYYYMMDDTHHMMSSZ>  (base = line before first '+', or whole line if no '+')
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VF="$ROOT/VERSION"
[[ -f "$VF" ]] || { echo "Missing $VF" >&2; exit 1; }
line="$(head -1 "$VF" | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
base="${line%%+*}"
suffix="$(date -u +%Y%m%dT%H%M%SZ)"
new="${base}+${suffix}"
printf '%s\n' "$new" > "$VF"
echo "$new"
