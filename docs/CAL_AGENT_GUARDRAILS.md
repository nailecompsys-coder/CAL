# CAL Agent Guardrails — Anti-Drift / Anti-Hallucination

Last updated: 2026-07-09

**Purpose:** Keep Cursor, Grok, Codex, and human developers from inventing paths, features, stacks, or APIs that do not exist in this repo.

Read this file **before** any CAL coding session, alongside `CLAUDE.md` and `docs/ai/CURSOR_CONTEXT.md`.

---

## 1. Ground Truth (Do Not Guess)

| Fact | Truth |
|------|-------|
| Git root | `/Users/donnaile/dev/CAL` |
| Production host | `192.168.5.62` → `/opt/cal` |
| Public URL | `https://cal.midfloridasurgical.com` |
| Backend source | `server/` (not `cal-app/`, not `app/`) |
| Production iOS | `ios/CALNative/` — **pure SwiftUI only** |
| Production Android target | `android/` — **Jetpack Compose** (not production until parity) |
| Android bridge (temporary) | `legacy-react-native/` — Android only, no iOS |
| Retired folder | `/Users/donnaile/dev/CAL-retired-20260707` — **never edit** |
| Legacy Atlas host | `192.168.20.10` — CAL retired there; do not deploy |
| Active compose | `docker-compose.standalone.yml` on `.62` |
| Legacy compose | `docker-compose.yml` with `atlas-net` — old host only |

If a path is not in this table or `README_ACTIVE_WORKSPACE.md`, **stop and verify** before editing.

---

## 2. Stack Decisions (Locked)

| Lane | Technology | Status |
|------|------------|--------|
| Admin + surgeon web | FastAPI + Jinja2 + Tailwind | Production |
| Native API | FastAPI JSON under `/api/native/*` | Production |
| iOS | SwiftUI in `ios/` | Production / TestFlight |
| iOS colors | **Asset Catalog + `ClinicalPalette` only** | NO-PASS: no `Color(red:)` / hex / UIColor RGB — see `.cursor/rules/swift-color-standard.mdc` |
| Android target | Jetpack Compose in `android/` | **Must mirror iOS exactly** |
| Android bridge | Expo in `legacy-react-native/` | Temporary until Compose ships |
| React Native iOS | **Blocked** | Never TestFlight |
| Admin UI framework | **No React, no Vite, no npm build for portal** | Locked |
| bcrypt | `4.0.1` pinned | Never upgrade |
| RVU | Separate app at `/home/dnaile748/rvu/` | Do not import or modify |

**Hallucination trap:** Agents often assume `cal-app/`, `cal-native/`, Expo iOS, or React admin UI. None of these are active.

---

## 3. Source-of-Truth Hierarchy

When documents conflict, follow this order:

1. `docs/cal-native-parity-ledger.md` — what ships on each platform
2. `docs/cal-native-stack-guardrails.md` — lane rules
3. `docs/APP_REFERENCE.md` — routes, models, run commands
4. `docs/imported/top-level/cal-contract-inventory.md` — locked API/auth contracts
5. `ios/CALNative/*.swift` — **UI spec for Android Compose parity**
6. `server/tests/test_native_*.py` — API shape truth
7. `legacy-react-native/src/services/calApi.ts` — API reference only, not UI spec

**Android must mimic `ios/`, not `legacy-react-native/` UI.** Legacy RN is a workflow reference for API calls only.

---

## 4. Anti-Hallucination Rules for Agents

### Before writing code

- [ ] Confirm Git root: `git rev-parse --show-toplevel` → `/Users/donnaile/dev/CAL`
- [ ] Run `make doctor`
- [ ] Read `memory.md` for session state
- [ ] Identify which **lane** you are touching: `server/`, `ios/`, `android/`, or `legacy-react-native/`
- [ ] If native/API: read parity ledger row for that workflow
- [ ] If UI: read `ios/CALNative/` equivalent screen first for Android work

### Never do without explicit approval

- Deploy to production (`make deploy-cal-standalone`)
- Change `SECRET_KEY`, bcrypt, or auth cookie semantics
- Run `docker compose down` on legacy host (kills shared postgres)
- Add Expo/Pods/React Native to `ios/`
- Add iOS config to `legacy-react-native/`
- Invent endpoints not in `APP_REFERENCE.md` or parity ledger
- Commit `.env`, SQL dumps, APKs, IPAs, `node_modules`, build artifacts
- Expose one surgeon's data to another surgeon
- Add Epic release/give-back/cancel to Block OR (Epic owns these)

### Never assume exists

- CI pipeline (not configured yet)
- Alembic migrations (listed but unused)
- `cal-app/` or `cal-native/` paths (retired)
- Ollama or Atlas AI stack in CAL repo
- Android scheduler (not built)
- Portal surgeon assignment for Block OR (mobile-only by design)
+ ~~Portal surgeon assignment for Block OR~~ — **superseded**: portal admin can assign/clear via same `or_block_service` as mobile (Phase 1 portal parity)
- Personal item CRUD in iOS (display-only from `/api/native/home` today)

### Every native/API change must include

1. Backend contract test if API touched (`server/tests/test_native_*.py`)
2. Parity ledger update (`docs/cal-native-parity-ledger.md`)
3. `./scripts/check-native-guardrails.sh` passes
4. `make test-local` passes

---

## 5. Android Parity Rule (Non-Negotiable)

**Jetpack Compose must mimic iOS SwiftUI to a T.**

| iOS spec | Android requirement |
|----------|---------------------|
| 3 sections via title menu: Schedule, Time Off, Patients | Same — **not** 5 bottom tabs |
| No Today / Messages / Profile tabs | Delete mock tabs from `MainActivity.kt` |
| Day / Week / Month segmented control in Schedule | Required |
| Call coverage sheet from on-call row | Required |
| Time off: month pills + request form | Required |
| Patients: 7-day Aprima range | Required |
| Alerts: banner overlay + inbox sheet | Required |
| Sign out in section title menu | Required |
| Face ID unlock on relaunch | Required (Android BiometricPrompt) |
| Scheduler role: separate shell after scheduler OTP | Required |
| Clinical Trust palette + glass cards | Match `CALNativeComponents.swift` |
| API client | Mirror `NativeCALClient.swift` endpoints exactly |

**Forbidden in Android production code:**

- Hardcoded surgeon names ("Chris Johnson", etc.)
- `ScreenPlaceholder` for shipped workflows
- Mock data for schedule, patients, or time off
- Inventing screens not in iOS (`Messages`, `Profile`, standalone `Today` tab)

---

## 6. Scheduler Rules (Mobile + Portal)

### Role split (do not blur)

| Actor | Portal (`server/templates/admin/`) | Mobile (`ios/` + future `android/`) |
|-------|-------------------------------------|---------------------------------------|
| Admin / superadmin | Create open Block OR blocks | N/A |
| Scheduler role | View Block OR week grid (read-only) | Assign/clear surgeons via scheduler OTP |
| Surgeon | See assigned blocks on clinic schedule | See Block OR on native home schedule |

### Scheduler mobile endpoints (locked)

```
POST /api/native/scheduler/otp/request
POST /api/native/scheduler/otp/verify
GET  /api/native/scheduler/home?start=&end=
GET  /api/native/scheduler/blocks/{id}
POST /api/native/scheduler/blocks/{id}/assign
POST /api/native/scheduler/blocks/{id}/clear
```

### Scheduler portal endpoints (locked)

```
GET  /admin/block-or
POST /admin/block-or/create          (admin/superadmin only)
GET  /admin/scheduler-availability   (admin only, needs nav link)
```

### Not in scope (Epic owns)

- Block release, give-back, cancel
- AH report state
- PHI in scheduler payloads

---

## 7. Verification Gates (Run, Don't Skip)

### Swift color NO-PASS (always)

- **Rule file:** `.cursor/rules/swift-color-standard.mdc` (`alwaysApply: true`)
- **Allowed:** `ClinicalPalette.*`, `Color("Clinical…")` asset names, system semantics (`.primary`, `.secondary`, `.white`, …)
- **Forbidden:** `Color(red:green:blue:)`, hex literals as colors, `UIColor(red:…)` in `ios/**/*.swift`
- **To add a color:** create `Images.xcassets/ClinicalName.colorset` → expose on `ClinicalPalette` → use that name in views
- **Gate:** `./scripts/check-native-guardrails.sh` fails the repo if any forbidden constructor appears under `ios/`

```sh
# Every session
make doctor
./scripts/check-native-guardrails.sh

# Before commit (native or API)
make test-local

# Before release/deploy
./scripts/check-native-guardrails.sh --release

# iOS proof
xcodebuildmcp simulator build --project-path ios/CALNative.xcodeproj --scheme CALNative

# Android proof
cd android && ./gradlew :app:assembleDebug
```

---

## 8. Session Close Checklist

Update `memory.md` with:

- What lane was touched
- Which parity ledger rows changed
- Which gates passed
- What is blocked on Don approval
- Any new locked decisions

---

## 9. Quick "Am I Hallucinating?" Test

Ask yourself:

1. Does this file path exist under `/Users/donnaile/dev/CAL`? → `ls` it
2. Does this endpoint exist in `server/app/routers/`? → grep it
3. Does iOS already do this? → read `ios/CALNative/` first for Android
4. Is this feature in the parity ledger? → if not, add it before coding
5. Am I editing a retired folder? → stop

If any answer is uncertain, **read the file — do not invent.**
