#!/usr/bin/env bash
# Align service worker cache name with VERSION so PWA clients drop old static caches after deploy.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VF="$ROOT/VERSION"
SW="$ROOT/app/static/sw.js"
[[ -f "$VF" ]] || { echo "Missing $VF" >&2; exit 1; }
[[ -f "$SW" ]] || { echo "Missing $SW" >&2; exit 1; }
V="$(tr -d '[:space:]' < "$VF")"
# Safe cache id: letters, digits, hyphens only
slug=$(printf '%s' "$V" | sed 's/[^a-zA-Z0-9]/-/g')
# macOS sed vs GNU: use perl for portable in-place edit
perl -i -pe "s/^const CACHE_NAME = 'cal-[^']+'/const CACHE_NAME = 'cal-${slug}-static'/" "$SW"
echo "sw.js CACHE_NAME -> cal-${slug}-static"
