# Mid Florida Surgical Cal — local deploy helpers (run from repo root)
.PHONY: deploy-cal deploy-cal-standalone verify-cal bump-only compile

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
	@python3 -m compileall -q app && echo OK compileall
