#!/usr/bin/env bash
# Read-only Docker/runtime diagnostic for CAL.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
cd "$REPO_ROOT" || exit 1

ok() { printf 'OK   %s\n' "$*"; }
warn() { printf 'WARN %s\n' "$*"; }
fail() { printf 'FAIL %s\n' "$*"; }
info() { printf 'INFO %s\n' "$*"; }

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

run_capture() {
  "$@" 2>/dev/null
}

env_file="$REPO_ROOT/.env"
if [[ ! -f "$env_file" ]]; then
  env_file="$REPO_ROOT/.env.example"
fi

compose_file="docker-compose.yml"
compose_label="legacy atlas"
if [[ "${CAL_STANDALONE:-}" == "1" ]]; then
  compose_file="docker-compose.standalone.yml"
  compose_label="standalone (CAL_STANDALONE=1)"
fi

echo "CAL Docker Doctor"
echo "================="
echo

echo "Repo"
echo "----"
info "cwd: $(pwd)"
git_root="$(run_capture git rev-parse --show-toplevel || true)"
if [[ -n "$git_root" ]]; then
  ok "git root: $git_root"
else
  fail "not inside a Git worktree"
fi

branch="$(run_capture git rev-parse --abbrev-ref HEAD || true)"
commit="$(run_capture git rev-parse --short HEAD || true)"
if [[ -n "$branch" && -n "$commit" ]]; then
  ok "git: $branch @ $commit"
else
  warn "could not read Git branch/commit"
fi

if [[ -n "$(run_capture git status --short || true)" ]]; then
  warn "worktree has uncommitted changes"
else
  ok "worktree clean"
fi

version_file="$ROOT/VERSION"
expected_version=""
if [[ -f "$version_file" ]]; then
  expected_version="$(tr -d '[:space:]' < "$version_file")"
  ok "server/VERSION: $expected_version"
else
  warn "missing server/VERSION"
fi
echo

echo "Docker"
echo "------"
docker_ok=0
if have_cmd docker; then
  ok "docker command found: $(command -v docker)"
  if docker version >/dev/null 2>&1; then
    ok "docker daemon reachable"
    docker_ok=1
  else
    warn "docker command exists, but daemon is not reachable"
  fi
else
  warn "docker command not found"
fi

compose_ok=0
if have_cmd docker && docker compose version >/dev/null 2>&1; then
  ok "docker compose available: $(docker compose version --short 2>/dev/null || docker compose version)"
  compose_ok=1
else
  warn "docker compose is not available"
fi
echo

echo "Compose"
echo "-------"
if [[ "$docker_ok" == "1" && "${CAL_STANDALONE:-}" != "1" ]]; then
  atlas_net=0
  atlas_default=0
  if docker network inspect atlas-net >/dev/null 2>&1; then atlas_net=1; fi
  if docker network inspect atlas_default >/dev/null 2>&1; then atlas_default=1; fi
  if [[ "$atlas_net" == "1" && "$atlas_default" == "1" ]]; then
    ok "atlas networks present; legacy atlas compose is usable"
  else
    warn "atlas networks missing; standalone compose is expected"
    compose_file="docker-compose.standalone.yml"
    compose_label="standalone (atlas networks missing)"
  fi
fi

if [[ -f "$env_file" ]]; then
  info "env file: ${env_file#$REPO_ROOT/}"
else
  warn "no .env or .env.example found"
fi
info "compose mode: $compose_label"
info "compose file: $compose_file"

if [[ "$compose_ok" == "1" && -f "$env_file" ]]; then
  if (cd "$REPO_ROOT" && COMPOSE_PROJECT_NAME=cal docker compose --env-file "$env_file" -f "$compose_file" config --quiet); then
    ok "compose config validates"
  else
    fail "compose config failed validation"
  fi
else
  warn "skipping compose config validation"
fi
echo

echo "Runtime"
echo "-------"
if [[ "$docker_ok" == "1" ]]; then
  for container in cal_api cal_postgres cal_db; do
    cid="$(docker ps -aq --filter "name=^/${container}$" 2>/dev/null | head -n 1)"
    if [[ -z "$cid" ]]; then
      warn "$container: not found"
      continue
    fi
    state="$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || true)"
    image="$(docker inspect -f '{{.Config.Image}}' "$container" 2>/dev/null || true)"
    image_id="$(docker inspect -f '{{.Image}}' "$container" 2>/dev/null || true)"
    if [[ "$state" == "running" ]]; then
      ok "$container: running image=${image:-unknown} image_id=${image_id:0:19}"
    else
      warn "$container: ${state:-unknown} image=${image:-unknown} image_id=${image_id:0:19}"
    fi
    if [[ "$container" == "cal_api" ]]; then
      ports="$(docker port cal_api 3005/tcp 2>/dev/null | tr '\n' ' ' || true)"
      if [[ -n "$ports" ]]; then
        ok "cal_api port 3005: $ports"
      else
        warn "cal_api port 3005 is not published"
      fi
    fi
  done
else
  warn "skipping runtime checks because Docker is unavailable"
fi
echo

echo "Health"
echo "------"
health_url="${CAL_HEALTH_URL:-http://127.0.0.1:3005/health}"
if have_cmd curl; then
  body="$(curl -sf --max-time 3 "$health_url" 2>/dev/null || true)"
  if [[ -n "$body" ]]; then
    ok "$health_url responded"
    actual_version="$(printf '%s' "$body" | python3 -c "import json,sys; print(str(json.load(sys.stdin).get('version','')).strip())" 2>/dev/null || true)"
    if [[ -n "$actual_version" ]]; then
      info "health version: $actual_version"
      if [[ -n "$expected_version" && "$actual_version" == "$expected_version" ]]; then
        ok "health version matches server/VERSION"
      elif [[ -n "$expected_version" ]]; then
        fail "health version does not match server/VERSION ($expected_version)"
      else
        warn "cannot compare health version without server/VERSION"
      fi
    else
      warn "health response did not include parseable version"
    fi
  else
    warn "$health_url is not reachable"
  fi
else
  warn "curl not found; skipping health check"
fi
echo

echo "Safety"
echo "------"
example_env="$REPO_ROOT/.env.example"
if [[ -f "$example_env" ]]; then
  suspicious_env="$(
    awk -F= '
      /^(SECRET_KEY|DATABASE_URL|ADMIN_PASSWORD|TEXTBELT_KEY|VAPID_PRIVATE_KEY|WASABI_KEY_ID|WASABI_SECRET)=/ {
        value=$2
        for (i=3; i<=NF; i++) value=value "=" $i
        if (value == "" || value ~ /^#/ || value ~ /change_me/ || value ~ /^your-/ || value ~ /example/ || value ~ /placeholder/) next
        if (length(value) >= 16 || value ~ /^postgresql:\/\//) print $1
      }
    ' "$example_env"
  )"
  if [[ -n "$suspicious_env" ]]; then
    warn ".env.example appears to contain production-looking secrets; replace with placeholders and rotate if live"
  else
    ok ".env.example does not contain obvious production-looking secrets"
  fi
else
  warn ".env.example missing"
fi

warn "do not run: docker compose down, docker system prune, or bare docker compose up --build"
ok "preferred commands: make doctor, make verify-cal, make deploy-cal-standalone"
