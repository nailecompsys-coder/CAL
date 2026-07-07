# CAL Restructure Phase 11 Top-Level Promotion

Phase 11 promotes `/Users/donnaile/dev/CAL` into the final local CAL Git root and moves stale outer folders into a retired sibling directory.

## Final Active Local Root

```text
/Users/donnaile/dev/CAL
```

Active folders:

```text
server/
ios/
android/
legacy-react-native/
docs/
scripts/
```

The `.git` directory now lives directly under `/Users/donnaile/dev/CAL`.

## Retired Local Reference

Old loose folders and files were moved, not deleted:

```text
/Users/donnaile/dev/CAL-retired-20260707/
```

Contents include:

```text
cal-native/
android-compose-prototype/
docs/
cursor/
cal-web/
IMG_2565.png
README_ACTIVE_WORKSPACE.md
```

The retired folder is intentionally outside the active Git root because it contains old nested Git state, local environment files, caches, APKs, and other local-only artifacts.

## Production Path

Production remains:

```text
/opt/cal
```

No production path rename was made in this phase.

## Current Commands

Backend tests:

```sh
cd /Users/donnaile/dev/CAL
./scripts/test-local.sh
```

Production deploy:

```sh
cd /opt/cal
NO_BUMP=1 CAL_STANDALONE=1 ./server/scripts/rebuild-cal-api.sh
```

iOS source:

```text
/Users/donnaile/dev/CAL/ios
```

Android Compose source:

```text
/Users/donnaile/dev/CAL/android
```

Android Expo bridge:

```text
/Users/donnaile/dev/CAL/legacy-react-native
```

## Guardrails

- Do not move retired folders back into the active repo.
- Do not commit `.env`, SQL dumps, APKs, IPAs, `.expo`, `node_modules`, Gradle caches, DerivedData, or old nested `.git` folders.
- Do not combine this filesystem cleanup with feature work, TestFlight, Expo release, or Aprima worker implementation.
