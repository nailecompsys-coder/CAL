#!/usr/bin/env bash
# Keep server/VERSION as a clean product version (no +UTC build suffix).
# Strips any existing +build metadata; does not append a timestamp.
# Edit VERSION manually when releasing a new product version (e.g. 2.0 → 2.1).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VF="$ROOT/VERSION"
[[ -f "$VF" ]] || { echo "Missing $VF" >&2; exit 1; }
line="$(head -1 "$VF" | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
base="${line%%+*}"
[[ -n "$base" ]] || { echo "VERSION is empty" >&2; exit 1; }
printf '%s\n' "$base" > "$VF"
echo "$base"
