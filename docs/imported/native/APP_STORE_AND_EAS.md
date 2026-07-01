# MFSA CAL — App Store Connect, EAS, and TestFlight

This file records the identifiers needed for **non-interactive** `eas submit`, **local EAS builds**, and **Apple CLI uploads** (`xcrun altool` / Transporter). Source: App Store Connect API (`altool --list-apps`) and Expo project linkage.

## Expo / EAS

| Item | Value |
|------|--------|
| Expo account (owner) | `ncsystems` |
| EAS project slug | `cal-native` |
| Full project name | `@ncsystems/cal-native` |
| EAS project UUID | `98f62090-f436-49c5-b758-07f371011061` |

`eas.json` references `submit.testflight.ios.ascAppId` for non-interactive submit.

## App Store Connect (CAL Native iOS)

| Item | Value |
|------|--------|
| **ASC App ID** (`ascAppId` for EAS submit) | `6764657615` |
| App name (ASC) | `CALNative` |
| Bundle ID | `com.midfloridasurgical.calnative` |
| SKU | `calnative` |

## App Store Connect API key (upload / automation)

| Item | Value |
|------|--------|
| Key ID | `MND49KG5B5` |
| Private key file (this Mac) | `$HOME/.appstoreconnect/private_keys/AuthKey_MND49KG5B5.p8` |
| **Issuer ID** (Users and Access → Integrations → Keys) | `69a6de75-b1ba-47e3-e053-5b8c7c11a4d1` |

### Upload IPA with Apple CLI (no EAS)

```bash
export ASC_ISSUER_ID="69a6de75-b1ba-47e3-e053-5b8c7c11a4d1"
xcrun altool --upload-app \
  -f "/path/to/CALNative.ipa" \
  -t ios \
  --apiKey MND49KG5B5 \
  --apiIssuer "$ASC_ISSUER_ID"
```

### List apps (sanity check)

```bash
xcrun altool --list-apps --apiKey MND49KG5B5 --apiIssuer "69a6de75-b1ba-47e3-e053-5b8c7c11a4d1"
```

## Local Xcode path (preferred when EAS local credentials are flaky)

1. Open `ios/CALNative.xcworkspace`, scheme **CALNative**, configuration **Release**.
2. **Product → Archive**, then **Distribute App → App Store Connect**.
3. Or use `xcodebuild -archivePath … archive` then `xcodebuild -exportArchive …` with `ExportOptions.plist` (see `app/build/testflight-*/ExportOptions.plist`).

## Production CAL API (native app default)

Release builds use: `https://cal.midfloridasurgical.com` (see `app/src/config/env.ts`).

## Server deploy (backend)

Production host after CAL VM cutover: **`cal-5.62` SSH alias** → `cal-prod-vm` (`192.168.5.62`). App root: `/opt/cal`.

```bash
ssh cal-5.62 'cd /opt/cal && NO_BUMP=1 make deploy-cal-standalone'
```

---

**Security:** The API key `.p8` file is secret; do not commit it. Issuer ID and ascAppId are not secret but treat keys as credentials.
