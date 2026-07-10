# Cursor / Grok Build Plan — From Codex

**Draft date:** 2026-07-09  
**Audience:** Cursor, Grok, and other AI coding agents continuing CAL after the Codex restructure  
**Git root:** `/Users/donnaile/dev/CAL`  
**Production host:** `192.168.5.62` → `/opt/cal` → `cal.midfloridasurgical.com`

---

## 1. What Codex Delivered

Codex completed a **12-phase filesystem restructure** (July 2026) that turned a loose multi-repo workspace into a single promoted Git root. Before touching code, understand what is already done vs what remains.

### Codex completed

| Phase | Outcome |
|-------|---------|
| 1–2 | Inventory + target layout (`server/`, `ios/`, `android/`, `legacy-react-native/`, `docs/`, `scripts/`) |
| 3 | Docs/AI consolidation into `docs/` |
| 4–5 | Native lane import; pure SwiftUI iOS detach (no Expo/Pods in `ios/`) |
| 6–7 | iOS simulator/archive proof; Android Compose + Expo bridge proof |
| 8–9 | Server path hardening; backend moved to `server/` with compatibility wrappers |
| 10–11 | Workspace quarantine; top-level Git promotion |
| 12 | Release readiness gates documented and proved from final root |

### Codex decisions locked in

- **SwiftUI** = production iOS (TestFlight from `ios/` only)
- **Jetpack Compose** = target Android (`android/`) — not production yet
- **Expo/React Native** = temporary Android bridge (`legacy-react-native/`) only
- **FastAPI + Jinja2** = production web + admin + native API (`server/`)
- **Web-first policy** until explicit native cutover sign-off
- **Parity ledger** must update with every native workflow change
- **Contract tests** required for every native API change (`server/tests/test_native_*.py`)

### Codex runtime hook

`server/scripts/test-local.sh` prefers the Codex Python runtime when present:

```text
/Users/donnaile/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
```

Cursor/Grok agents should use `make test-local` or `make test` from repo root — do not invent a separate test harness.

---

## 2. Workspace Map (Current Truth)

```
/Users/donnaile/dev/CAL/          ← single Git root
├── server/                       ← FastAPI, admin portal, surgeon PWA, native APIs
│   ├── app/
│   │   ├── main.py               entry point
│   │   ├── models.py             monolithic ORM (~20+ tables)
│   │   ├── routers/              ~30 router modules
│   │   ├── rules_engine/         scheduling conflict detection
│   │   ├── native_*              mobile API services
│   │   ├── admin_*               admin portal services
│   │   ├── templates/            Jinja2 HTML
│   │   └── static/               PWA (sw.js, manifest, icons)
│   ├── tests/                    27 unittest files
│   ├── scripts/                  deploy, doctor, rebuild, smoke
│   ├── Dockerfile
│   ├── VERSION
│   └── requirements.txt          all versions pinned
├── ios/                          ← SwiftUI production iOS (30 Swift files)
│   ├── CALNative.xcodeproj
│   └── CALNative/                pure SwiftUI — no Pods, no Expo
├── android/                      ← Jetpack Compose target (1 Kotlin file today)
│   └── app/src/main/.../MainActivity.kt
├── legacy-react-native/          ← Expo Android bridge only
│   ├── App.tsx
│   └── src/                      calApi.ts, tokenStore, types
├── docs/                         canonical documentation
│   ├── APP_REFERENCE.md          read before any server change
│   ├── cal-native-parity-ledger.md
│   ├── cal-native-stack-guardrails.md
│   ├── RELEASE_CHECKLIST.md
│   ├── DOCS_INDEX.md
│   ├── restructure-phase-*.md    historical restructure record
│   └── ai/                       agent context (this file)
├── scripts/
│   └── check-native-guardrails.sh  pre-commit/pre-release gate
├── .cursor/rules/                CLAUDE.md, build_app.md, PALETTES.md
├── CLAUDE.md                     session checklist
├── memory.md                     session state — update before closing
├── Makefile                      doctor, test, deploy, mac-dev targets
├── docker-compose.yml            legacy Atlas stack
├── docker-compose.standalone.yml target prod VM (.62)
└── docker-compose.mac-dev.yml    local Mac dev Postgres
```

**Retired (do not edit):** `/Users/donnaile/dev/CAL-retired-20260707/`

---

## 3. Agent Onboarding — Read Order

Every Cursor/Grok session must start here, in order:

| # | File | Why |
|---|------|-----|
| 1 | `CLAUDE.md` | Project guardrails, deploy rules, constraints |
| 2 | `memory.md` | Current session state and locked decisions |
| 3 | `docs/APP_REFERENCE.md` | Routes, models, run commands, templates |
| 4 | `docs/cal-native-stack-guardrails.md` | Native lane rules |
| 5 | `docs/cal-native-parity-ledger.md` | What ships on each platform |
| 6 | `.cursor/rules/PALETTES.md` | UI tokens (Clinical Trust palette) |
| 7 | `.cursor/rules/build_app.md` | ATLAS workflow |
| 8 | `docs/RELEASE_CHECKLIST.md` | Before any deploy or TestFlight |

**Before Docker/deploy/debug:** `make doctor` from repo root.

---

## 4. Release Lanes

| Lane | Source | Build command | Production? |
|------|--------|---------------|-------------|
| Backend + admin + native API | `server/` | `make deploy-cal-standalone` | **Yes** |
| iOS TestFlight | `ios/` | Xcode archive from `ios/CALNative.xcodeproj` | **Yes** |
| Android temporary | `legacy-react-native/` | `npm --prefix legacy-react-native run doctor` | Bridge only |
| Android target | `android/` | `cd android && ./gradlew :app:assembleDebug` | **No** — mock UI |
| Surgeon PWA | `server/app/templates/` + `static/` | Deployed with backend | **Yes** |

---

## 5. ATLAS Build Framework (Mapped to CAL)

Follow `.cursor/rules/build_app.md`. This section maps ATLAS steps to CAL-specific actions.

> **Naming note:** ATLAS here is the build **workflow acronym** (Architect, Trace, Link, Assemble, Stress-test) from `.cursor/rules/build_app.md`. It is unrelated to the retired `atlas-postgres` / `atlas-net` legacy stack on `192.168.20.10`. CAL production runs standalone on `192.168.5.62` and does not use the Atlas infrastructure.

### A — Architect

**Problem:** Surgical group needs call/clinic/surgical scheduling with admin portal + mobile clients.  
**Users:** 2 admins, ~11 surgeons, schedulers (Block OR lane).  
**Success:** Schedules assigned without conflicts; surgeons see today/week/month on mobile; admins manage via portal.  
**Constraints:** bcrypt 4.0.1 pinned; no React admin UI; web-first until cutover; PHI read-only from Aprima.

**UI surfaces:**

| Surface | Palette | Rules |
|---------|---------|-------|
| Admin portal | Clinical Trust | Sidebar + dense tables; no hardcoded hex |
| Surgeon PWA | Clinical Trust | Mobile glass + gradients |
| iOS SwiftUI | Clinical Trust (native tokens) | Stupid simple — Don's direction in `Changes to Calendar.md` |
| Android Compose | Match iOS | Not production until API integrated |

### T — Trace

**Data schema:** `server/app/models.py` — single source of truth. Key tables:

```
admin_users, surgeons, surgeon_devices, magic_links
call_rotations, clinic_schedules, surgeon_location_schedules
days_off, meetings, surgical_cases, patient_assignments
locations, call_groups, scheduling_rule_config
push_subscriptions, surgeon_otp_audit_log
schedule_change_events, or_blocks (scheduler lane)
```

**Integrations:**

| Service | Purpose | Location |
|---------|---------|----------|
| PostgreSQL | Primary DB | `server/app/database.py` |
| Aprima (pymssql) | Patient schedule read-through | `server/app/native_patient_schedule_service.py` |
| TextBelt | SMS OTP | `server/app/sms_service.py` |
| Wasabi S3 | DB backup | `server/app/wasabi_backup.py` |
| APNs / Web Push | Alerts | `server/app/push.py` |
| RVU (external) | Shared JWT + DB — do not modify | `/home/dnaile748/rvu/` |

**Native API contract surface:**

```
POST /api/surgeon/otp/request|verify
GET  /api/native/home
GET  /api/native/patient-schedule
POST /api/native/call-coverage
/api/native/request-off*
/api/native/push-token
/api/native/alerts/read
/surgeon/api/day-items*
/api/native/scheduler/*          (scheduler/admin identity)
```

### L — Link (Validate Before Building)

Run from `/Users/donnaile/dev/CAL`:

```sh
make doctor                                    # runtime state
./scripts/check-native-guardrails.sh           # lane hygiene
./scripts/test-local.sh                        # backend tests (27 files)
docker compose --env-file .env.example config  # compose resolves
```

**iOS link test:**

```sh
xcodebuildmcp simulator build \
  --project-path ios/CALNative.xcodeproj \
  --scheme CALNative --configuration Debug
```

**Android link test:**

```sh
cd android && ./gradlew :app:assembleDebug
npm --prefix legacy-react-native run doctor
```

All green before writing feature code.

### A — Assemble (Build Order)

**Always build in this order:**

1. **Database/model** — `server/app/models.py` + `migrate_*.py` if schema change
2. **Service layer** — `server/app/*_service.py` or `native_*_service.py`
3. **Router** — `server/app/routers/`
4. **Contract test** — `server/tests/test_native_*.py`
5. **Parity ledger** — `docs/cal-native-parity-ledger.md`
6. **Native client** — `ios/CALNative/` (Swift) or `android/` (Compose) or `legacy-react-native/` (bridge)
7. **Admin template** (if portal UI needed) — `server/app/templates/admin/`

**Never:**

- Put Aprima logic in `ios/`, `android/`, or `legacy-react-native/`
- Add Expo/Pods to `ios/`
- Add iOS config to `legacy-react-native/`
- Invent native workflows without a backend endpoint + contract test
- Use bare `docker compose up --build` — use `make deploy-cal-standalone`
- Auto-deploy without Don confirming

### S — Stress-test

**Backend:**

```sh
make test-local
make compile
./server/scripts/smoke-mac-dev.sh    # if mac-dev stack running
```

**Native guardrails:**

```sh
./scripts/check-native-guardrails.sh --release   # before deploy/TestFlight
```

**Manual acceptance (from `Changes to Calendar.md`):**

- Mobile: Good morning + name, today card, swipe left/right keeps TODAY focus
- Week view: tap day → single-day timeline (7am gradient, 30-min marks)
- Admin: simplify calendar, rename Surgeons → Physicians, dashboard cards
- OTP works email + phone; patient schedule times match Aprima Eastern

### V + M (when asked for prod hardening)

- Rate limiting on OTP/admin login (not yet implemented)
- CSRF on admin forms (not yet implemented)
- Alembic migrations (listed in requirements, unused)
- CI pipeline (no `.github/workflows` yet)

---

## 6. Build Phases — What Cursor/Grok Should Do Next

Phases are ordered by dependency. Do not skip gates.

### Phase 0 — Environment bootstrap (every session)

```sh
cd /Users/donnaile/dev/CAL
git status --short
git rev-parse --show-toplevel    # must be /Users/donnaile/dev/CAL
make doctor
```

Read `memory.md`. Update it before closing the session.

### Phase 1 — Backend stability (server/)

**Goal:** Keep production API stable while native/Android work continues.

| Task | Files | Gate |
|------|-------|------|
| Fix doc path drift in `docs/ai/CURSOR_CONTEXT.md` | `docs/ai/CURSOR_CONTEXT.md` | Review only |
| OTP rate limiting | `server/app/routers/surgeon_otp.py` | New test |
| Admin CSRF tokens | `server/app/routers/admin_*.py` | New test |
| Alembic adoption (or remove from requirements) | `server/app/migrate_*.py` | Migration plan doc |
| Production cutover to `.62` | `deploy/cutover_to_cal_vm.sh` | Don approval + parity check |
| Scheduler digest job | `server/scripts/send_scheduler_digest.py` | Manual cron on prod |

**Gate:** `./scripts/test-local.sh` + `make doctor` + Don approval for deploy.

### Phase 2 — iOS production polish (ios/)

**Goal:** Close TestFlight gaps from parity ledger.

| Workflow | Status | Cursor/Grok action |
|----------|--------|-------------------|
| Push alerts | Simulator done; needs TestFlight verify | APNs env, TestFlight test, update ledger |
| Scheduler Block OR | Simulator lane | TestFlight verify, ledger update |
| Face ID unlock | Production | Verify repeat-open flow |
| Daily timeline view | Partial | Implement Don's day-tap → timeline UX (`Changes to Calendar.md`) |
| Week/month labels | Partial | Spell out clinic/or/hospital names, not color-only pills |

**Gate:**

```sh
xcodebuildmcp simulator build --project-path ios/CALNative.xcodeproj --scheme CALNative
./scripts/check-native-guardrails.sh --release
```

Update `docs/cal-native-parity-ledger.md` in same commit.

### Phase 3 — Admin portal UX (server/templates/)

**Goal:** Implement Don's calendar simplification.

| Task | Source |
|------|--------|
| Rename Surgeons → Physicians | `Changes to Calendar.md` |
| Remove Specialty field | same |
| Calendar: filter by selected physician | same |
| Settings: Hospital + Clinic locations | same |
| Dashboard: On Call / Meetings / Days Off cards | same |
| Add Clinic Schedule and Rotation under Calendar | same |

**Gate:** Manual admin smoke test; `make test-local`; no native contract breakage.

### Phase 4 — Android Compose integration (android/)

**Goal:** Move from mock UI to real CAL APIs.

**Current state:** 461-line `MainActivity.kt` with hardcoded data. Zero API integration.

**Build order:**

1. Add Retrofit/Ktor client mirroring `legacy-react-native/src/services/calApi.ts`
2. OTP auth flow → secure token storage (EncryptedSharedPreferences)
3. `GET /api/native/home` → Today + schedule views
4. Time off, call coverage, patients, push — match parity ledger rows
5. Mark each row `Production` in ledger only after contract tests pass

**Gate:**

```sh
cd android && ./gradlew :app:assembleDebug
./scripts/check-native-guardrails.sh --release
```

Compose cannot ship until auth + schedule + time off + on-call + patients + push all use real APIs.

### Phase 5 — Android Expo bridge maintenance (legacy-react-native/)

**Goal:** Keep bridge alive until Compose parity approved.

- Android-only releases from this lane
- No iOS EAS profiles or TestFlight scripts
- Match SwiftUI workflows per parity ledger
- Deprecate when Phase 4 complete

**Gate:** `npm --prefix legacy-react-native run doctor`

### Phase 6 — Engineering hygiene

| Task | Priority |
|------|----------|
| Add `.github/workflows` — `make test-local` on PR | High |
| ESLint + `tsc --noEmit` for legacy-react-native | Medium |
| Swift unit tests for `NativeCALClient` | Medium |
| Deduplicate `docs/imported/` vs canonical docs | Low |
| Add `android/.gitignore` for build artifacts | Low |

---

## 7. Gate Commands Cheat Sheet

Run from `/Users/donnaile/dev/CAL`:

```sh
# Every session start
make doctor

# Before any commit touching native or backend API
./scripts/check-native-guardrails.sh
make test-local

# Before production deploy (commit + push first)
./scripts/check-native-guardrails.sh --release
make deploy-cal-standalone          # Don must approve
curl -sf https://cal.midfloridasurgical.com/health

# Before iOS TestFlight
xcodebuildmcp simulator build \
  --project-path ios/CALNative.xcodeproj \
  --scheme CALNative

# Before Android handoff
npm --prefix legacy-react-native run doctor
cd android && ./gradlew :app:assembleDebug

# Mac local dev stack
make mac-dev-up
make mac-dev-smoke
```

---

## 8. Commit Discipline

### What must be in the same commit

| Change type | Required co-changes |
|-------------|---------------------|
| Native workflow | `docs/cal-native-parity-ledger.md` |
| Native API shape | `server/tests/test_native_*.py` + ledger |
| Release path / build command | `docs/RELEASE_CHECKLIST.md` or phase doc |
| UI color/token | `.cursor/rules/PALETTES.md` reference only — use tokens |
| Session work | `memory.md` update before close |

### Never commit

- `.env`, `.env.mac-dev`, `cal_live.sql`, `cal_live.dump`
- `node_modules/`, `.expo/`, `build/`, `DerivedData/`, `.xcarchive`, `.ipa`, `.apk`
- PHI, credentials, SQL dumps
- Build artifacts from `ios/` or `android/`

---

## 9. Cursor vs Grok — Agent Roles

| Agent | Best for | CAL focus |
|-------|----------|-----------|
| **Cursor** | Multi-file edits, iOS via XcodeBuildMCP, terminal, PR workflow | Primary implementation agent |
| **Grok** | Architecture review, doc synthesis, critique, planning | Review + plan before Cursor executes |

### Recommended handoff pattern

1. **Grok** reads this plan + parity ledger → produces scoped task brief
2. **Cursor** implements in one lane (`server/`, `ios/`, `android/`) → runs gates
3. **Grok** reviews diff against guardrails + ledger
4. **Don** approves deploy/TestFlight
5. **Cursor** updates `memory.md` and commits

### Cursor-specific tooling

- XcodeBuildMCP for iOS simulator build/test
- `CallMcpTool` browser MCP for admin portal smoke tests
- `ReadLints` after Swift/Python edits
- Never use bare `docker compose up --build`

### Grok-specific tooling

- Full-doc reads for critique (`docs/CRITIQUE.md`, `docs/FULL_CRITIQUE_AND_REVIEW.md`)
- Cross-lane parity analysis
- Produce plans; do not deploy

---

## 10. Anti-Patterns (Codex Learned These the Hard Way)

1. **Editing retired folders** — `CAL-retired-20260707` is reference only
2. **Assuming `cal-app/` or `cal-native/` paths** — restructured to `server/`, `ios/`, etc.
3. **Mounting React Native on iOS** — SwiftUI is production; RN iOS is blocked
4. **Shipping Compose without API** — mock UI is not a release candidate
5. **Skipping parity ledger** — guardrails script may fail `--release`
6. **Combining server deploy + iOS archive in one commit** — phase docs forbid this
7. **Hardcoding colors** — use PALETTES.md tokens
8. **Changing bcrypt** — pinned at 4.0.1
9. **Modifying RVU auth/SECRET_KEY** — breaks SSO with RVU app
10. **Running `docker compose down` on legacy host** — kills shared `atlas-postgres`

---

## 11. Product Backlog (Don's Direction)

From `Changes to Calendar.md` — not yet fully implemented:

**Admin portal:**
- Single calendar screen; remove repetitive screens
- Surgeons → Physicians; remove Specialty; remove "Dr." prefix
- Calendar left-rail: ALL + individual physicians; selecting one filters view
- Settings: Hospital + Clinic locations hub
- Calendar submenu: Clinic Schedule + Rotation
- Dashboard: big On Call buttons, calendar button, card widgets (On Call, Meetings, Days Off)

**Mobile (iOS primary):**
- Stupid simple: Good morning + name; remove right badge
- Blue today card; swipe keeps TODAY focus (fix confusing empty-day copy)
- Fix tap-to-resize bug
- Week view: spell out clinic names (not just red/orange pills)
- Tap day → single-day timeline with time gradient (7am, 30-min marks)
- Future: patient names in schedule pills

**Research (conversation only, not code):**
- Survey other medical group calendars for UX ideas

---

## 12. Definition of Done

A Cursor/Grok build session is complete when:

- [ ] All gate commands pass for the touched lane(s)
- [ ] Parity ledger updated if native workflows changed
- [ ] Contract tests added/updated if API changed
- [ ] No artifacts staged (`check-native-guardrails.sh` clean)
- [ ] `memory.md` updated with completed / in-progress / next
- [ ] Don informed if deploy or TestFlight is needed (never auto-deploy)

---

## 13. Quick Reference

| Question | Answer |
|----------|--------|
| Where is the backend? | `server/` |
| Where is production iOS? | `ios/CALNative/` (SwiftUI) |
| Where is Android production? | Not yet — use `legacy-react-native/` bridge |
| Where is Android target? | `android/` (Compose, mock only) |
| How do I run tests? | `make test-local` |
| How do I deploy? | `make deploy-cal-standalone` (Don approves) |
| What doc is law for APIs? | `docs/APP_REFERENCE.md` + parity ledger |
| What must I read first? | `CLAUDE.md` → `memory.md` → `APP_REFERENCE.md` |
| Where did Codex leave off? | Phase 12 complete; lanes proved; prod cutover to `.62` in progress |
| What should Cursor/Grok do next? | Phase 1–3 above (backend hardening, iOS polish, admin UX) |

---

*This plan inherits from Codex restructure phases 1–12 and `docs/cal-native-stack-guardrails.md`. Update this file when release lanes, gates, or phase priorities change.*
