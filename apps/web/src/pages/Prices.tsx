import { PRICE_DAYS, daysBefore, displayName, formatDate, formatRupees, marketOnDay, type MarketPrices, type PriceSummary, type PricesResponse } from "@mandi/shared";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertsPanel } from "../components/AlertsPanel";
import { CalendarIcon } from "../components/Icons";
import { Sparkline } from "../components/Sparkline";
import { useApp } from "../lib/app-context";

const STATUS_STYLE = {
  fresh: "bg-leaf-soft text-leaf-ink",
  stale: "bg-turmeric-soft text-turmeric-ink",
  missing: "bg-sunken text-muted",
  sparse: "bg-turmeric-soft text-turmeric-ink",
} as const;

const STATUS_DOT = { fresh: "bg-leaf", stale: "bg-turmeric", missing: "bg-muted", sparse: "bg-turmeric" } as const;

export function PricesPage() {
  const { t } = useTranslation();
  const { api, meta, language, district } = useApp();
  const lang = language ?? "en";
  const [crop, setCrop] = useState("onion");
  const [data, setData] = useState<PricesResponse | null>(null);
  const [error, setError] = useState(false);
  // The last 7 days come in one request; choosing a day only picks from them.
  const [picked, setPicked] = useState(""); // "" = today; otherwise a day in the last 7 (yyyy-mm-dd)
  const dateInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setData(null);
    setError(false);
    api
      .prices(crop, PRICE_DAYS, district, null)
      .then(setData)
      .catch(() => setError(true));
  }, [api, crop, district]);

  const today = data?.as_of ?? new Date().toLocaleDateString("en-CA");
  const firstDay = daysBefore(today, PRICE_DAYS - 1);
  const day = picked && picked >= firstDay && picked < today ? picked : today;
  const allViews = data?.markets.map((m) => ({ m, view: marketOnDay(m, day, today, data.stale_after_days) })) ?? [];
  // Only markets with a real record; empty "no information" cards are left out.
  const views = allViews.filter((v) => v.view.point);
  // The demo banner only when every market shown is on demo prices.
  const withData = data?.markets.filter((m) => m.source) ?? [];
  const demo = withData.length > 0 && withData.every((m) => m.source === "synthetic");

  const openCalendar = () => {
    const input = dateInput.current;
    if (!input) return;
    try {
      input.showPicker();
    } catch {
      input.focus(); // older browsers: focusing the date input opens its picker
      input.click();
    }
  };

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-2xl font-bold tracking-tight">{t("prices.title")}</h2>
        <p className="text-sm text-muted">
          {data?.district && <>{displayName(meta?.districts?.find((d) => d.id === data.district), lang, data.district)} · </>}
          {t("prices.unit")} · {t("prices.trend")}
        </p>
      </div>
      <div>
        <label className="label" htmlFor="prices-crop">
          {t("ask.crop")}
        </label>
        <select id="prices-crop" className="input font-semibold" value={crop} onChange={(e) => setCrop(e.target.value)}>
          {(meta?.crops ?? [{ id: "onion", name: "Onion", names: {} }]).map((c) => (
            <option key={c.id} value={c.id}>
              {displayName(c, lang)}
            </option>
          ))}
        </select>
      </div>
      <div className="flex items-center justify-between gap-3">
        <p className="min-w-0 text-lg font-semibold" aria-live="polite">
          {day === today ? t("prices.todayPrices", { date: formatDate(today, lang) }) : t("prices.pricesFor", { date: formatDate(day, lang) })}
        </p>
        <div className="relative flex shrink-0 items-center gap-2">
          {day !== today && (
            <button type="button" className="text-sm font-medium text-leaf-ink underline-offset-2 hover:underline" onClick={() => setPicked("")}>
              {t("prices.backToToday")}
            </button>
          )}
          <button type="button" className="btn-ghost w-12 px-0" onClick={openCalendar} aria-label={t("prices.calendar")} title={t("prices.calendar")}>
            <CalendarIcon />
          </button>
          {/* No visible field: the calendar button opens this input's date picker. */}
          <input
            ref={dateInput}
            type="date"
            tabIndex={-1}
            aria-hidden
            className="pointer-events-none absolute bottom-0 right-0 h-px w-px opacity-0"
            min={firstDay}
            max={today}
            value={day}
            onChange={(e) => setPicked(e.target.value)}
          />
        </div>
      </div>
      {data && views.length === 0 && (
        <p className="rounded-r-lg border-l-[3px] border-turmeric bg-turmeric-soft/70 px-3 py-2.5 text-sm text-turmeric-ink">{t("prices.noData")}</p>
      )}
      {demo && (
        <p className="rounded-r-lg border-l-[3px] border-turmeric bg-turmeric-soft/70 px-3 py-2.5 text-sm text-turmeric-ink">{t("prices.demo")}</p>
      )}
      {error && (
        <p role="alert" className="rounded-r-lg border-l-[3px] border-chilli bg-chilli-soft px-3 py-2.5 text-chilli-ink">
          {t("ask.error")}
        </p>
      )}
      {!data && !error && (
        <div className="space-y-3" aria-hidden>
          {[0, 1].map((i) => (
            <div key={i} className="card h-36 animate-pulse bg-sunken" />
          ))}
        </div>
      )}
      <ul className="space-y-3">
        {views.map(({ m, view }) => (
          <li key={m.market} className="card overflow-hidden p-0">
            <div className="flex items-start justify-between gap-3 p-4 pb-3">
              <div className="min-w-0">
                <h3 className="truncate text-lg font-semibold leading-tight">{displayName({ id: m.market, name: m.market_name, names: m.names }, lang)}</h3>
                <span className={`chip mt-1.5 ${STATUS_STYLE[view.status]}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[view.status]}`} aria-hidden />
                  {t(`prices.status.${view.status === "sparse" ? "stale" : view.status}`)}
                  {view.ageDays !== null && view.ageDays > 0 ? ` · ${t("prices.daysOld", { count: view.ageDays })}` : ""}
                </span>              </div>
              <Sparkline values={m.history.map((h) => h.modal)} label={t("prices.trend")} />
            </div>
            {view.point ? (
              <dl className="grid grid-cols-[auto_1fr_auto] items-end gap-4 bg-board px-4 py-3 text-sm">
                <div>
                  <dt className="eyebrow text-white/55">{t("prices.modal")}</dt>
                  <dd className="num text-2xl font-semibold leading-none text-board-ink">₹{formatRupees(view.point.modal, lang)}</dd>
                </div>
                <div>
                  <dt className="eyebrow text-white/55">{t("prices.range")}</dt>
                  <dd className="num whitespace-nowrap text-white/85">
                    {formatRupees(view.point.min, lang)}–{formatRupees(view.point.max, lang)}
                  </dd>
                </div>
                <div className="text-right">
                  <dt className="eyebrow text-white/55">{t("prices.date")}</dt>
                  <dd className="num text-white/85">{formatDate(view.point.date, lang)}</dd>
                </div>
              </dl>
            ) : null}
            {view.point && view.point.date !== day && (
              <p className="border-t border-line px-4 py-2 text-sm text-turmeric-ink">{t("prices.lastAvailable", { date: formatDate(view.point.date, lang) })}</p>
            )}
            <PriceRecords market={m} lang={lang} />
          </li>
        ))}
      </ul>
      {data?.summary && <SummaryCard summary={data.summary} data={data} lang={lang} />}
      <AlertsPanel crop={crop} district={data?.district ?? district} />
    </div>
  );
}

function PriceRecords({ market, lang }: { market: MarketPrices; lang: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  if (market.history.length === 0) return null;
  return (
    <div className="border-t border-line">
      <button type="button" className="w-full px-4 py-2.5 text-left text-sm font-medium text-leaf-ink" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {open ? t("prices.hideRecords") : `${t("prices.records")} (${market.history.length})`}
      </button>
      {open && (
        <div className="max-h-72 overflow-y-auto px-4 pb-3">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface text-left text-muted">
              <tr>
                <th className="py-1.5 font-medium">{t("prices.date")}</th>
                <th className="py-1.5 text-right font-medium">{t("prices.modal")}</th>
                <th className="py-1.5 text-right font-medium">{t("prices.range")}</th>
              </tr>
            </thead>
            <tbody className="num">
              {[...market.history].reverse().map((h) => (
                <tr key={h.date} className="border-t border-line">
                  <td className="py-1.5">{formatDate(h.date, lang)}</td>
                  <td className="py-1.5 text-right font-semibold">₹{formatRupees(h.modal, lang)}</td>
                  <td className="whitespace-nowrap py-1.5 text-right text-muted">
                    {formatRupees(h.min, lang)}–{formatRupees(h.max, lang)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SummaryCard({ summary, data, lang }: { summary: PriceSummary; data: PricesResponse; lang: string }) {
  const { t } = useTranslation();
  const marketName = (id: string) => {
    const m = data.markets.find((x) => x.market === id);
    return m ? displayName({ id: m.market, name: m.market_name, names: m.names }, lang) : id;
  };
  const change = summary.change_pct;
  return (
    <section className="card space-y-3 p-4" aria-labelledby="price-summary">
      <div>
        <h3 id="price-summary" className="text-lg font-semibold">
          {t("prices.summaryTitle")}
        </h3>
        <p className="text-sm text-muted">
          {formatDate(summary.from, lang)} – {formatDate(summary.to, lang)} · {t("prices.daysWithPrices", { count: summary.days_with_prices })}
        </p>
      </div>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-muted">{t("prices.lowest")}</dt>
          <dd className="num text-lg font-semibold">₹{formatRupees(summary.lowest.modal, lang)}</dd>
          <dd className="text-xs text-muted">
            {formatDate(summary.lowest.date, lang)} · {marketName(summary.lowest.market)}
          </dd>
        </div>
        <div>
          <dt className="text-muted">{t("prices.highest")}</dt>
          <dd className="num text-lg font-semibold">₹{formatRupees(summary.highest.modal, lang)}</dd>
          <dd className="text-xs text-muted">
            {formatDate(summary.highest.date, lang)} · {marketName(summary.highest.market)}
          </dd>
        </div>
        <div>
          <dt className="text-muted">{t("prices.average")}</dt>
          <dd className="num text-lg font-semibold">₹{formatRupees(summary.average, lang)}</dd>
        </div>
        {change !== null && (
          <div>
            <dt className="text-muted">{t("prices.change")}</dt>
            <dd className={`num text-lg font-semibold ${change > 0 ? "text-leaf-ink" : change < 0 ? "text-chilli-ink" : ""}`}>
              {change > 0 ? "▲" : change < 0 ? "▼" : ""} {Math.abs(change)}%
            </dd>
          </div>
        )}
      </dl>
    </section>
  );
}
