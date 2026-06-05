# Mid Florida Surgical Cal — local deploy helpers (run from repo root)
PYTHON ?= python3

.PHONY: deploy-cal deploy-cal-standalone verify-cal bump-only compile test test-local mac-dev-up mac-dev-down mac-dev-status mac-dev-logs mac-dev-smoke

deploy-cal:
	@./scripts/rebuild-cal-api.sh

# Same as deploy-cal but never uses atlas-net (docker-compose.standalone.yml only)
deploy-cal-standalone:
	@CAL_STANDALONE=1 ./scripts/rebuild-cal-api.sh

verify-cal:
	@./scripts/verify-cal-api.sh

bump-only:
	@./scripts/bump-version.sh && ./scripts/sync-sw-cache-name.sh

compile:
	@$(PYTHON) -m compileall -q app && echo OK compileall

test:
	@$(PYTHON) -m unittest discover -s tests

test-local:
	@./scripts/test-local.sh

# Mac local dev lifecycle (docker-compose.mac-dev.yml)
mac-dev-up:
	@./scripts/bootstrap-mac-dev.sh

mac-dev-down:
	@docker compose -f docker-compose.mac-dev.yml down

mac-dev-status:
	@docker compose -f docker-compose.mac-dev.yml ps

mac-dev-logs:
	@docker compose -f docker-compose.mac-dev.yml logs -f --tail=200 cal_api

mac-dev-smoke:
	@./scripts/smoke-mac-dev.sh
