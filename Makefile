# Mid Florida Surgical Cal — local deploy helpers (run from repo root)
PYTHON ?= python3

.PHONY: doctor deploy-cal deploy-cal-standalone verify-cal bump-only compile test test-local mac-dev-up mac-dev-down mac-dev-status mac-dev-logs mac-dev-smoke

doctor:
	@./server/scripts/doctor.sh

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
