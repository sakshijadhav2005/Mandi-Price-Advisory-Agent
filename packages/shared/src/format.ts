import type { Named } from "./types";

const LOCALES: Record<string, string> = { en: "en-IN", hi: "hi-IN", mr: "mr-IN" };

export function locale(lang: string): string {
  return LOCALES[lang] ?? "en-IN";
}

/** Rupees with Indian digit grouping (1,23,456). Uses Latin digits for readability on low-end devices. */
export function formatRupees(value: number | null | undefined, lang = "en"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return new Intl.NumberFormat(`${locale(lang)}-u-nu-latn`, { maximumFractionDigits: 0 }).format(Math.round(value));
}

export function formatDate(iso: string, lang = "en"): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat(`${locale(lang)}-u-nu-latn`, { day: "numeric", month: "short" }).format(new Date(y, m - 1, d));
}

export function displayName(item: Named | undefined, lang: string, fallback = ""): string {
  if (!item) return fallback;
  return item.names?.[lang] ?? item.name;
}
