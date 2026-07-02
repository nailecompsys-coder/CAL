# CAL Documentation Index

Last updated: 2026-07-01

## Canonical Location During Restructure

Until CAL is migrated to a single top-level Git root, canonical tracked documentation lives in:

```text
/Users/donnaile/dev/CAL/cal-app/docs/
```

Do not create new long-lived docs in loose top-level folders. Add them here so they are committed and pushed.

## Restructure Docs

| Document | Purpose |
|---|---|
| `restructure-phase-1-inventory.md` | Ground-truth pre-move inventory |
| `restructure-phase-2-target-layout.md` | Final filesystem and Git target map |
| `restructure-phase-3-docs-ai-consolidation.md` | Docs/AI import record |
| `restructure-phase-4-native-lane-import.md` | Native lane source import record |
| `restructure-phase-5-ios-swiftui-detach.md` | Pure SwiftUI iOS detach record |
| `restructure-phase-6-ios-release-proof.md` | iOS simulator, UI, and archive proof |
| `restructure-phase-7-android-lane-proof.md` | Android Compose and Expo bridge proof |
| `restructure-phase-8-server-path-hardening.md` | Server path hardening before physical move |
| `restructure-phase-9-server-layout-move.md` | Backend/admin portal move into `server/` with compatibility wrappers |
| `restructure-phase-10-workspace-quarantine.md` | Local workspace quarantine and active path map |
| `cal-native-stack-guardrails.md` | Native lane and release guardrails |
| `cal-native-parity-ledger.md` | Platform parity ledger |

## Operations / Production Docs

| Document | Purpose |
|---|---|
| `DISASTER_RECOVERY.md` | Backup/restore and recovery notes |
| `MFSA_SERVER_SET_MASTER.md` | Server role map |
| `APP_REFERENCE.md` | App reference |
| `RULES_ENGINE_SPEC.md` | Scheduling rules engine |

## Imported Transition Docs

The following folders contain tracked copies of docs that previously lived outside the production Git repo:

```text
docs/imported/top-level/
docs/imported/native/
docs/imported/web-placeholder/
docs/ai/
```

Treat these as preserved source material until they are reviewed, deduplicated, and moved into the final `docs/` or `ai/` folders after the top-level Git root migration.
