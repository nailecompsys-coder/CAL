import Constants from "expo-constants";

function normalizeCalApiUrl(raw: string): string {
  let u = raw.trim().replace(/\/+$/, "");
  // Fix common typos in hostname (manual .env / simulator cache issues)
  u = u.replace(/midlforidasurgical\.com/gi, "midfloridasurgical.com");
  u = u.replace(/midlflorida/gi, "midflorida");
  return u;
}

const extra = Constants.expoConfig?.extra as { apiBaseUrl?: string } | undefined;
const productionBase = "https://cal.midfloridasurgical.com";

const rawBase = __DEV__
  ? process.env.EXPO_PUBLIC_CAL_API_BASE_URL ?? extra?.apiBaseUrl ?? productionBase
  : productionBase;

export const API_BASE_URL = normalizeCalApiUrl(rawBase);
