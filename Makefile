# Mid Florida Surgical Cal — local deploy helpers (run from repo root)
PYTHON ?= python3

.PHONY: doctor seed-guardrail-demo deploy-cal deploy-cal-standalone verify-cal bump-only compile test test-local mac-dev-up mac-dev-down mac-dev-status mac-dev-logs mac-dev-smoke mac-dev-restore-dump scheduler-digest-dry-run

doctor:
	@./server/scripts/doctor.sh

seed-guardrail-demo:
	@cd server && ./.venv-test/bin/python scripts/seed_guardrail_demo.py

deploy-cal:
	@./server/scripts/rebuild-cal-api.sh

# Same as deploy-cal but never uses atlas-net (docker-compose.standalone.yml only)
deploy-cal-standalone:
	@CAL_STANDALONE=1 ./server/scripts/rebuild-cal-api.sh

verify-cal:
	@./server/scripts/verify-cal-api.sh

bump-only:
	@./server/scripts/bump-version.sh && ./server/scripts/sync-sw-cache-name.sh

compile:
	@cd server && $(PYTHON) -m compileall -q app && echo OK compileall

test:
	@cd server && PYTHONPATH=. $(PYTHON) -m unittest discover -s tests

test-local:
	@./server/scripts/test-local.sh

# Mac local dev lifecycle (docker-compose.mac-dev.yml)
mac-dev-up:
	@./server/scripts/bootstrap-mac-dev.sh

mac-dev-down:
	@cd server && docker compose --env-file ../.env.mac-dev -f docker-compose.mac-dev.yml down

mac-dev-status:
	@cd server && docker compose --env-file ../.env.mac-dev -f docker-compose.mac-dev.yml ps

mac-dev-logs:
	@cd server && docker compose --env-file ../.env.mac-dev -f docker-compose.mac-dev.yml logs -f --tail=200 cal_api

mac-dev-smoke:
	@./server/scripts/smoke-mac-dev.sh

# Wipe LOCAL Docker DB and load cal_live.dump (or DUMP=path). Requires CONFIRM=1.
# Never touches production. See docs/LOCAL_DEV_REAL_DATA.md
mac-dev-restore-dump:
	@CONFIRM=$${CONFIRM:-} ./server/scripts/restore-mac-dev-dump.sh $${DUMP:-}

# Build digest payload + recipient list without sending email (runs in mac-dev cal_api)
scheduler-digest-dry-run:
	@docker cp server/scripts/send_scheduler_digest.py cal_api:/tmp/send_scheduler_digest.py
	@docker exec -w /app cal_api python -c "import importlib.util,sys; sys.path.insert(0,'/app'); spec=importlib.util.spec_from_file_location('d','/tmp/send_scheduler_digest.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); raise SystemExit(m.main(['--dry-run']))"
