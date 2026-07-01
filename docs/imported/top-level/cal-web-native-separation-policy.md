# CAL Web/Native Separation Policy (Web-First)

Last updated: 2026-04-28

## Decision

CAL remains a web app in active service until the native frontend is fully validated and explicitly approved for cutover.

## Operating Model

- `cal-app` is the current live web runtime track.
- `cal-web` is the explicit web lane for documentation and future web-only assets.
- `cal-native` is a separate development lane for native frontend work.

## Non-Negotiable Guardrails

- Do not break or remove existing CAL web routes:
  - `/admin/*`
  - `/surgeon/*`
  - `/api/*`
  - `/api/surgeon/otp/*`
- Do not change CAL web auth/session behavior while native is in parallel development:
  - web cookies remain supported
  - bearer fallback behavior remains compatible where currently used
- No native-only dependency may be required for web runtime startup.
- No native release can replace web as primary without an explicit go-live decision.

## Native Track Rules

- Native app work must use separate docs, backlog, and release checklist.
- Native API compatibility changes must be additive and backward-compatible with web.
- If an endpoint change risks web regression, block it until a compatibility plan is documented.

## Cutover Readiness Criteria (Before Any Web Replacement Discussion)

- Native auth flow validated end-to-end.
- Native critical workflows validated under real user testing.
- Error/incident runbook exists for native production.
- Rollback plan can return traffic/control to web immediately.
- Stakeholder sign-off completed.

