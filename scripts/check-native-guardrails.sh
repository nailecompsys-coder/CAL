#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE_REF="${BASE_REF:-HEAD}"
MODE="${1:-}"
STRICT_RELEASE=0
if [[ "$MODE" == "--release" ]]; then
  STRICT_RELEASE=1
elif [[ -n "$MODE" ]]; then
  echo "Usage: $0 [--release]" >&2
  exit 2
fi

failures=()

add_failure() {
  failures+=("$1")
}

repo_changes() {
  local repo="$1"
  {
    git -C "$repo" diff --name-only "$BASE_REF" -- 2>/dev/null || true
    git -C "$repo" ls-files --others --exclude-standard 2>/dev/null || true
  } | sort -u
}

matches_any() {
  local data="$1"
  local pattern="$2"
  printf '%s\n' "$data" | grep -E "$pattern" >/dev/null 2>&1
}

check_artifacts() {
  local label="$1"
  local data="$2"
  local artifact_pattern='(^|/)(node_modules|\.expo|build|DerivedData)(/|$)|\.(xcarchive|ipa|apk)$|(^|/).*\.xcarchive(/|$)|(^|/)dist(/|$)|(^|/)web-build(/|$)'
  local bad
  bad="$(printf '%s\n' "$data" | grep -E "$artifact_pattern" || true)"
  if [[ -n "$bad" ]]; then
    add_failure "$label has staged/changed/untracked build artifacts or dependency cache files:
$bad"
  fi
}

require_clean_and_pushed() {
  local repo="$1"
  local label="$2"
  if [[ -n "$(git -C "$repo" status --short)" ]]; then
    add_failure "$label is not clean. Commit, stash, or discard local changes before release."
    return
  fi
  local branch upstream head upstream_head
  branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD)"
  upstream="$(git -C "$repo" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
  if [[ -z "$upstream" ]]; then
    add_failure "$label branch '$branch' has no upstream. Push it before release."
    return
  fi
  head="$(git -C "$repo" rev-parse HEAD)"
  upstream_head="$(git -C "$repo" rev-parse "$upstream" 2>/dev/null || true)"
  if [[ "$head" != "$upstream_head" ]]; then
    add_failure "$label HEAD is not the same commit as $upstream. Push/pull until local and upstream match."
  fi
}

native_changes="$(repo_changes "$ROOT")"
check_artifacts "cal-native/app" "$native_changes"

native_source_pattern='^(App\.tsx|index\.ts|app\.json|eas\.json|package(-lock)?\.json|src/|ios/CALNative/|ios/CALNative\.xcodeproj/|ios/CALNative\.xcworkspace/|ios/Podfile|ios/Podfile\.lock)'
native_ledger_pattern='^docs/cal-native-(parity-ledger|stack-guardrails)\.md$'
metadata_pattern='^(app\.json|eas\.json|package(-lock)?\.json|ios/CALNative\.xcodeproj/project\.pbxproj|ios/CALNative/Info\.plist)'

ledger_touched=0
if matches_any "$native_changes" "$native_ledger_pattern"; then
  ledger_touched=1
fi

if matches_any "$native_changes" "$native_source_pattern" && [[ "$ledger_touched" != "1" ]]; then
  add_failure "Native source changed without updating docs/cal-native-parity-ledger.md or docs/cal-native-stack-guardrails.md."
fi

if matches_any "$native_changes" "$metadata_pattern" && [[ "$ledger_touched" != "1" ]]; then
  add_failure "Native build metadata changed without a parity ledger/guardrail note."
fi

if matches_any "$native_changes" '^ios/' && matches_any "$native_changes" '^(App\.tsx|index\.ts|src/|app\.json|eas\.json|package(-lock)?\.json)' && [[ "$ledger_touched" != "1" ]]; then
  add_failure "Both iOS SwiftUI and Expo/React Native lanes changed without a ledger note explaining cross-platform parity."
fi

BACKEND_REPO="${BACKEND_REPO:-$ROOT/../../cal-app}"
if [[ -d "$BACKEND_REPO/.git" ]]; then
  app_changes="$(repo_changes "$BACKEND_REPO")"
  check_artifacts "cal-app" "$app_changes"
  backend_native_pattern='^(app/native_|app/routers/native_api\.py|app/routers/surgeon_day_items\.py|app/routers/surgeon_otp\.py|app/routers/api_push\.py|app/push\.py|app/sms_service\.py)'
  native_contract_test_pattern='^tests/(test_native_|test_surgeon_otp_|test_push_)'
  if matches_any "$app_changes" "$backend_native_pattern" && ! matches_any "$app_changes" "$native_contract_test_pattern"; then
    add_failure "Backend native API/auth/push files changed without a native contract test update."
  fi
  if [[ "$STRICT_RELEASE" == "1" ]]; then
    require_clean_and_pushed "$BACKEND_REPO" "cal-app"
  fi
else
  echo "WARN: backend repo not found at $BACKEND_REPO; checked native repo only." >&2
fi

if [[ "$STRICT_RELEASE" == "1" ]]; then
  require_clean_and_pushed "$ROOT" "cal-native/app"
fi

if [[ ${#failures[@]} -gt 0 ]]; then
  echo "CAL native guardrails FAILED" >&2
  echo >&2
  for failure in "${failures[@]}"; do
    echo "- $failure" >&2
    echo >&2
  done
  exit 1
fi

echo "CAL native guardrails OK"
if [[ "$STRICT_RELEASE" == "1" ]]; then
  echo "Release mode: Git state is clean and pushed for checked repos."
else
  echo "Working mode: no native drift, missing contract tests, or artifact issues detected."
fi
