# CAL Restructure Phase 9 Server Layout Move

Phase 9 moves the production backend/admin portal runtime into the target `server/` lane while preserving old root commands as compatibility wrappers.

## What Moved

- `app/` -> `server/app/`
- `tests/` -> `server/tests/`
- `scripts/` server/deploy helpers -> `server/scripts/`
- `deploy/`, `imports/`, `tools/` -> `server/`
- `Dockerfile`, `VERSION`, `requirements.txt`, `tailwind.config.js`, and server compose files -> `server/`

The SwiftUI iOS lane, Jetpack Compose lane, Expo Android bridge, docs, and root native guardrails stay at the repository root.

## Compatibility Kept

Old root script entry points still work through wrappers:

```sh
./scripts/rebuild-cal-api.sh
./scripts/test-local.sh
./scripts/verify-cal-api.sh
```

Root compose files also remain as compatibility entry points and build from `./server`.

## Deploy Path

Preferred backend deploy path is now:

```sh
cd /opt/cal
NO_BUMP=1 CAL_STANDALONE=1 ./server/scripts/rebuild-cal-api.sh
```

The old root path remains valid:

```sh
cd /opt/cal
NO_BUMP=1 CAL_STANDALONE=1 ./scripts/rebuild-cal-api.sh
```

## Safety Updates

- Server scripts read `.env` and `.env.mac-dev` from the repo root.
- Server compose files use `../.env` and `../.env.mac-dev`.
- Server deploy scripts force `COMPOSE_PROJECT_NAME=cal` by default so moving compose files under `server/` does not create a second Docker project, network, or Postgres volume.
- Git metadata in Docker labels still comes from the repository root.
- Backup and DR scripts archive/restore from the repository root, not only the `server/` folder.
- Native guardrails now look for backend native API and contract tests under `server/app` and `server/tests`.

## Verification

Passed:

```sh
./scripts/test-local.sh
./scripts/check-native-guardrails.sh
docker compose --env-file .env.example config
cd server && docker compose --env-file ../.env.example -f docker-compose.standalone.yml config
git diff --check
```

Local Docker image build could not be run because the local Docker daemon was not running in this shell. Production Docker rebuild must be verified on `cal-5.62` before this phase is considered deployed.

## Rollback

Rollback is a normal Git revert of this commit while production still uses `/opt/cal` as the clone root. No database migration is included in this phase.
