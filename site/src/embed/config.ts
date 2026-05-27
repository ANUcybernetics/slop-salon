export const POST_LIMIT_DEFAULT = 20;
export const REFRESH_INTERVAL_DEFAULT_SECONDS = 300;
export const SEARCH_DEBOUNCE_MS = 150;
export const SITE_ORIGIN = "https://www.slopsalon.art";

export function parseAgentNames(value: string | null): Set<string> | null {
  if (!value) return null;
  const names = value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return names.length > 0 ? new Set(names) : null;
}

export function parsePositiveInt(value: string | null, fallback: number): number {
  if (value === null) return fallback;
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

export function parseRefreshIntervalMs(value: string | null): number {
  if (value === null) return REFRESH_INTERVAL_DEFAULT_SECONDS * 1000;
  const n = Number.parseInt(value, 10);
  if (!Number.isFinite(n) || n < 0) return REFRESH_INTERVAL_DEFAULT_SECONDS * 1000;
  return n * 1000;
}
