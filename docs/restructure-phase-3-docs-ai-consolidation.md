# CAL Restructure Phase 3 Docs / AI Consolidation

Last updated: 2026-07-01

## Purpose

Phase 3 consolidates scattered documentation and AI context into the tracked production repository without moving runtime code. This phase intentionally imports copies instead of deleting the old loose files, because `/Users/donnaile/dev/CAL` is not the single Git root yet.

## What Changed

Loose docs and AI context were imported into `cal-app/docs` so they are now protected by Git on `main`.

Imported from top-level loose docs:

```text
/Users/donnaile/dev/CAL/docs/CODEBASE_REVIEW.md
/Users/donnaile/dev/CAL/docs/MFSA_SERVER_SET_MASTER.md
/Users/donnaile/dev/CAL/docs/cal-contract-inventory.md
/Users/donnaile/dev/CAL/docs/cal-mac-dev-svp-readiness.md
/Users/donnaile/dev/CAL/docs/cal-prod-5.62-migration.md
/Users/donnaile/dev/CAL/docs/cal-web-native-separation-policy.md
```

Imported from native loose docs:

```text
/Users/donnaile/dev/CAL/cal-native/docs/APP_STORE_AND_EAS.md
```

Imported from web placeholder:

```text
/Users/donnaile/dev/CAL/cal-web/README.md
```

Imported from AI/Cursor context:

```text
/Users/donnaile/dev/CAL/cursor/CURSOR_CONTEXT.md
```

## New Tracked Locations

```text
cal-app/docs/imported/top-level/
cal-app/docs/imported/native/
cal-app/docs/imported/web-placeholder/
cal-app/docs/ai/
```

## Canonical Docs During Transition

Until `/Users/donnaile/dev/CAL` becomes the single Git root, the canonical tracked docs are inside:

```text
/Users/donnaile/dev/CAL/cal-app/docs/
```

The loose top-level copies remain as source-history breadcrumbs only. Do not edit loose copies for new work. Edit the tracked copies under `cal-app/docs`.

## Why Originals Were Not Deleted

The originals are outside the current production Git repo. Deleting them now would be a local filesystem cleanup only, not a clean Git-tracked move. They should be removed in the final filesystem cleanup after the new top-level Git root exists and the tracked docs are verified.

## Phase 3 No-Code-Move Rule

Phase 3 does not move:

- `cal-app`
- `cal-native/app`
- `android-compose-prototype`
- SwiftUI source
- Expo/React Native source
- Compose source
- Production `/opt/cal`
- Docker/compose files
- Aprima code

## Acceptance Criteria

- Loose docs copied into tracked docs.
- AI/Cursor context copied into tracked docs.
- Canonical docs location documented.
- No runtime code moved.
- Guardrails pass.
- Backend tests pass.
- Commit pushed to `main`.
