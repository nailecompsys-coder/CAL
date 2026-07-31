#!/usr/bin/env bash
# ONLY working Android Expo/dev-client path for CAL.
# Do NOT use: --localhost, expo start --android, Expo Go.
#
# =============================================================================
# AGENTS: DO NOT RESTART THE EMULATOR WHILE DON IS USING IT.
# =============================================================================
# This script is intentionally NON-DESTRUCTIVE when the stack is already healthy.
# - If emulator-5554 is already `device` + boot_completed=1, do NOT restart it.
# - If Metro is already listening on *:8081, do NOT kill/restart Metro.
# - NEVER pkill qemu / kill the emulator from this script (or ad-hoc agent shells).
# - Prefer soft reload over am force-stop unless LAUNCH=1 is set.
# Killing adb/qemu/metro mid-session is why Don's sim "disappears" while he uses it.
# =============================================================================
set -euo pipefail

AVD="${AVD:-CAL_Pixel_8}"
PACKAGE="${PACKAGE:-com.midfloridasurgical.calnative}"
ACTIVITY="${ACTIVITY:-.MainActivity}"
APP_DIR_NAME="${APP_DIR_NAME:-legacy-react-native}"
METRO_PORT="${METRO_PORT:-8081}"
EXPO_GO_PKG="host.exp.exponent"
# LAUNCH=1 → force-stop + cold start the app. Default: reverse + soft reload if already foreground.
LAUNCH="${LAUNCH:-0}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${ROOT}/${APP_DIR_NAME}"
ANDROID_HOME="${ANDROID_HOME:-${HOME}/Library/Android/sdk}"
export ANDROID_HOME ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"
export PATH="${ANDROID_HOME}/emulator:${ANDROID_HOME}/platform-tools:${ANDROID_HOME}/cmdline-tools/latest/bin:${PATH}"

METRO_LOG="${METRO_LOG:-/tmp/cal-metro.log}"
EMU_LOG="${EMU_LOG:-/tmp/cal-emulator.log}"

log() { printf '[run-expo-android-sim] %s\n' "$*"; }
die() { printf '[run-expo-android-sim] ERROR: %s\n' "$*" >&2; exit 1; }

# Detach a command so it survives agent/shell exit (macOS has no setsid binary).
detach() {
  local pidfile="$1"; shift
  python3 - "$pidfile" "$@" <<'PY'
import os, sys, subprocess
pidfile = sys.argv[1]
cmd = sys.argv[2:]
if os.fork() > 0:
    sys.exit(0)
os.setsid()
if os.fork() > 0:
    sys.exit(0)
with open(os.devnull, "rb") as devnull:
    p = subprocess.Popen(cmd, stdin=devnull, start_new_session=True)
with open(pidfile, "w") as f:
    f.write(str(p.pid))
os._exit(0)
PY
}

[[ -d "$APP_DIR" ]] || die "App dir missing: $APP_DIR"
command -v adb >/dev/null || die "adb not on PATH (ANDROID_HOME=$ANDROID_HOME)"
command -v emulator >/dev/null || die "emulator not on PATH"

serial=""
pick_serial() {
  serial="$(adb devices 2>/dev/null | awk '/^emulator-[0-9]+\tdevice$/{print $1; exit}')"
}

emulator_healthy() {
  # Prefer emulator-5554 when present; otherwise any booted emulator.
  local cand boot
  if adb devices 2>/dev/null | awk '/^emulator-5554\tdevice$/{found=1} END{exit !found}'; then
    cand="emulator-5554"
  else
    pick_serial
    cand="$serial"
  fi
  [[ -n "$cand" ]] || return 1
  boot="$(adb -s "$cand" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"
  [[ "$boot" == "1" ]] || return 1
  serial="$cand"
  return 0
}

app_likely_foreground() {
  # Best-effort: resumed/focused activity matches our package (do not force-stop if so).
  local dump
  dump="$(adb -s "$serial" shell dumpsys activity activities 2>/dev/null || true)"
  printf '%s' "$dump" | grep -qE "mResumedActivity.*${PACKAGE}|topResumedActivity.*${PACKAGE}|mFocusedApp.*${PACKAGE}"
}

ensure_emulator() {
  # NON-DESTRUCTIVE: never kill/restart a healthy emulator.
  # NEVER pkill qemu / emulator from this script.
  if emulator_healthy; then
    log "Emulator already healthy: $serial (boot_completed=1) — leaving it alone"
    return 0
  fi

  pick_serial
  if [[ -n "$serial" ]]; then
    log "Emulator $serial present but not fully booted — waiting (no restart)"
    local i boot
    for i in $(seq 1 120); do
      boot="$(adb -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"
      if [[ "$boot" == "1" ]]; then
        log "Boot complete: $serial"
        return 0
      fi
      sleep 2
    done
    die "Timed out waiting for boot on $serial (refusing to kill/restart)"
  fi

  log "No emulator device — starting AVD $AVD once (will not kill later)"
  : >"$EMU_LOG"
  # Double-fork detach; NEVER kill this later while Don is using the sim.
  detach /tmp/cal-emulator.pid bash -c \
    "exec emulator -avd \"$AVD\" -no-snapshot-save -netdelay none -netspeed full >>\"$EMU_LOG\" 2>&1"
  sleep 1
  log "emulator launch pid=$(cat /tmp/cal-emulator.pid 2>/dev/null || echo '?') (log: $EMU_LOG)"

  local i
  for i in $(seq 1 120); do
    if emulator_healthy; then
      log "Boot complete: $serial"
      return 0
    fi
    sleep 2
  done
  die "Timed out waiting for $AVD / emulator-5554"
}

metro_listening() {
  lsof -nP -iTCP:"$METRO_PORT" -sTCP:LISTEN 2>/dev/null | grep -qE 'TCP \*|TCP 0\.0\.0\.0'
}

metro_pid() {
  lsof -nP -iTCP:"$METRO_PORT" -sTCP:LISTEN -t 2>/dev/null | head -1
}

ensure_metro() {
  # NON-DESTRUCTIVE: if already on *:8081, do not kill/restart.
  if metro_listening; then
    log "Metro already on *:${METRO_PORT} pid=$(metro_pid) — leaving it alone"
    return 0
  fi

  # Only kill wrong bind (localhost-only) — healthy * bind is never killed above.
  local pids
  pids="$(lsof -nP -iTCP:"$METRO_PORT" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    log "Port ${METRO_PORT} occupied but not * / 0.0.0.0 — killing wrong bind: ${pids}"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 1
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
  fi

  log "Starting Metro *:8081 from ${APP_DIR} (host lan — NOT --localhost)"
  : >"$METRO_LOG"
  # NEVER --localhost. NEVER expo start --android.
  detach /tmp/cal-metro.pid bash -c \
    "cd \"$APP_DIR\" && exec npx expo start --port $METRO_PORT --lan >>\"$METRO_LOG\" 2>&1"
  sleep 1
  local i
  for i in $(seq 1 60); do
    if metro_listening; then
      log "Metro ready pid=$(metro_pid) log=$METRO_LOG"
      return 0
    fi
    sleep 1
  done
  die "Metro failed to listen on *:${METRO_PORT} — see $METRO_LOG"
}

ensure_package() {
  if adb -s "$serial" shell pm path "$PACKAGE" >/dev/null 2>&1; then
    log "Package installed: $PACKAGE"
    return 0
  fi
  log "Package missing — CI=1 npx expo run:android --no-bundler (Metro separate)"
  (
    cd "$APP_DIR"
    CI=1 npx expo run:android --no-bundler
  )
  adb -s "$serial" shell pm path "$PACKAGE" >/dev/null 2>&1 \
    || die "Install failed: $PACKAGE still missing"
}

soft_reload_js() {
  # Double-R is the classic Metro reload; also try broadcast used by RN.
  adb -s "$serial" shell input text "RR" 2>/dev/null || true
  adb -s "$serial" shell am broadcast -a com.facebook.react.BROADCAST_RELOAD 2>/dev/null || true
}

adb_reverse_and_launch() {
  log "Force-stop Expo Go ($EXPO_GO_PKG) if present"
  adb -s "$serial" shell am force-stop "$EXPO_GO_PKG" 2>/dev/null || true

  log "adb reverse tcp:${METRO_PORT} tcp:${METRO_PORT}"
  adb -s "$serial" reverse "tcp:${METRO_PORT}" "tcp:${METRO_PORT}"
  adb -s "$serial" reverse --list || true

  if [[ "$LAUNCH" == "1" ]]; then
    log "LAUNCH=1 — force-stop + cold start ${PACKAGE}/${ACTIVITY}"
    adb -s "$serial" shell am force-stop "$PACKAGE" 2>/dev/null || true
    adb -s "$serial" shell am start -n "${PACKAGE}/${ACTIVITY}"
  elif app_likely_foreground; then
    log "App already foreground ($PACKAGE) — reverse ok; soft reload (no force-stop)"
    soft_reload_js
  else
    log "App not foreground — start ${PACKAGE}/${ACTIVITY} without force-stop"
    adb -s "$serial" shell am start -n "${PACKAGE}/${ACTIVITY}"
  fi

  local i
  for i in $(seq 1 30); do
    if adb -s "$serial" logcat -d -t 80 2>/dev/null | grep -q 'Running main'; then
      log "Confirmed: Running main"
      break
    fi
    sleep 1
  done

  log "DONE serial=$serial metro_pid=$(metro_pid) package=$PACKAGE LAUNCH=$LAUNCH"
  log "AVD=$AVD Metro=*:${METRO_PORT} reverse ok — native only (not Expo Go)"
}

main() {
  ensure_emulator
  ensure_metro
  ensure_package
  adb_reverse_and_launch
}

main "$@"
