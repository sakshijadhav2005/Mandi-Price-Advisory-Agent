import type { MarketPrices, MarketStatus, PricePointDto } from "./types";

/** How many days the Prices screen keeps: today and the 6 days before it. */
export const PRICE_DAYS = 7;

/** yyyy-mm-dd `n` days before `iso` (calendar arithmetic, no time zone shift). */
export function daysBefore(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d - n));
  return t.toISOString().slice(0, 10);
}

function daysBetween(from: string, to: string): number {
  const ms = (s: string) => {
    const [y, m, d] = s.split("-").map(Number);
    return Date.UTC(y, m - 1, d);
  };
  return Math.round((ms(to) - ms(from)) / 86_400_000);
}

export interface DayView {
  /** The price shown for the chosen day: that day's record, else the last one before it. */
  point: PricePointDto | null;
  status: MarketStatus;
  /** Days between the chosen day and the price's own date (0 = a price from that day). */
  ageDays: number | null;
}

/**
 * One market on one chosen day, from a 7-day prices response. `today` is the response's
 * `as_of`, so the window moves forward by itself each day.
 */
export function marketOnDay(m: MarketPrices, day: string, today: string, staleAfterDays: number): DayView {
  const upTo = m.history.filter((h) => h.date <= day);
  let point: PricePointDto | null = upTo.length ? upTo[upTo.length - 1] : null;
  // Nothing in the window up to that day: the server's last real price before the window.
  if (!point && m.latest && m.latest.date <= day) point = m.latest;
  if (!point) return { point: null, status: "missing", ageDays: null };
  const ageDays = daysBetween(point.date, day);
  // Today keeps the server's status (it also knows about sparse reporting).
  const status: MarketStatus = day === today ? m.status : ageDays <= staleAfterDays ? "fresh" : "stale";
  return { point, status, ageDays };
}
