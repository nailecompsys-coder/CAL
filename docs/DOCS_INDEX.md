# CAL Documentation Index

Last updated: 2026-07-07

## Canonical Location

CAL is now promoted to a single top-level Git root. Canonical tracked documentation lives in:

```text
/Users/donnaile/dev/CAL/docs/
```

Do not create new long-lived docs in retired folders under `/Users/donnaile/dev/CAL-retired-20260707`.

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
| `restructure-phase-11-top-level-promotion.md` | Promotion to final local top-level Git root |
| `restructure-phase-12-release-readiness.md` | Release lane proof from the final top-level Git root |
| `cal-native-stack-guardrails.md` | Native lane and release guardrails |
| `cal-native-parity-ledger.md` | Platform parity ledger |
| `CAL_AGENT_GUARDRAILS.md` | Anti-drift / anti-hallucination rules for all agents |
| `SCHEDULER_AND_ANDROID_EXECUTION_PLAN.md` | Scheduler portal/mobile + Android-iOS parity build plan |
| `BLOCK_OR_SCHEDULER_AUDIT.md` | Block OR logic/screen audit — intent vs Codex code, bugs, continue path |
| `MOBILE_BLOCK_OR_CREATE_PLAN.md` | Scheduler mobile create open blocks — **plan only, hold for Don verify** |
| `LOCAL_DEV_REAL_DATA.md` | Load real dump into Mac-dev; portal + DEBUG sim share localhost dataset |

## Agent Build Plans

| Document | Purpose |
|---|---|
| `ai/CURSOR_GROK_BUILD_FROM_CODEX.md` | Cursor/Grok build plan continuing from the Codex restructure — read order, lanes, phases, gates |
| `ai/CURSOR_CONTEXT.md` | Agent bootstrap context (contract docs, high-value files) |

## Operations / Production Docs

| Document | Purpose |
|---|---|
| `DISASTER_RECOVERY.md` | Backup/restore and recovery notes |
| `MFSA_SERVER_SET_MASTER.md` | Server role map |
| `APP_REFERENCE.md` | App reference |
| `RELEASE_CHECKLIST.md` | Backend, iOS, Android, and beta release gates |
| `RULES_ENGINE_SPEC.md` | Scheduling rules engine |

## Imported Transition Docs

The following folders contain tracked copies of docs that previously lived outside the production Git repo:

```text
docs/imported/top-level/
docs/imported/native/
docs/imported/web-placeholder/
docs/ai/
```

Treat these as preserved source material until they are reviewed and deduplicated.
