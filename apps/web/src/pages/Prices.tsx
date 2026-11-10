import { displayName, formatDate, formatRupees, type PricesResponse } from "@mandi/shared";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertsPanel } from "../components/AlertsPanel";
import { Sparkline } from "../components/Sparkline";
import { useApp } from "../lib/app-context";

const STATUS_STYLE = {
  fresh: "bg-leaf-100 text-leaf-900 dark:bg-leaf-900/60 dark:text-leaf-100",
  stale: "bg-amber-100 text-amber-900 dark:bg-amber-900/50 dark:text-amber-100",
  missing: "bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-300",
  sparse: "bg-amber-100 text-amber-900",
} as const;

export function PricesPage() {
  const { t } = useTranslation();
  const { api, meta, language, district } = useApp();
  const lang = language ?? "en";
  const [crop, setCrop] = useState("onion");
  const [data, setData] = useState<PricesResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    setData(null);
    setError(false);
    api
      .prices(crop, 30, district)
      .then(setData)
      .catch(() => setError(true));
  }, [api, crop, district]);

  const demo = data?.markets.some((m) => m.source === "synthetic");

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-bold">
        {t("prices.title")}
        {data?.district && (
          <span className="ml-2 text-base font-normal text-stone-500">
            · {displayName(meta?.districts?.find((d) => d.id === data.district), lang, data.district)}
          </span>
        )}
      </h2>
      <div className="flex gap-2" role="tablist">
        {(meta?.crops ?? [{ id: "onion", name: "Onion", names: {} }]).map((c) => (
          <button
            key={c.id}
            role="tab"
            aria-selected={crop === c.id}
            className={crop === c.id ? "btn-primary" : "btn-ghost"}
            onClick={() => setCrop(c.id)}
          >
            {displayName(c, lang)}
          </button>
        ))}
      </div>
      <p className="text-sm text-stone-500 dark:text-stone-400">
        {t("prices.unit")} · {t("prices.trend")}
      </p>
      {demo && <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-950 dark:bg-amber-950/40 dark:text-amber-100">{t("prices.demo")}</p>}
      {error && <p className="text-red-700">{t("ask.error")}</p>}
      {!data && !error && <div className="card h-40 animate-pulse" />}
      <ul className="space-y-3">
        {data?.markets.map((m) => (
          <li key={m.market} className="card">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="truncate text-lg font-semibold">{displayName({ id: m.market, name: m.market_name, names: m.names }, lang)}</h3>
                <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[m.status]}`}>
                  {t(`prices.status.${m.status === "sparse" ? "stale" : m.status}`)}
                  {m.age_days !== null && m.age_days > 0 ? ` · ${t("prices.daysOld", { count: m.age_days })}` : ""}
                </span>
              </div>
              <Sparkline values={m.history.map((h) => h.modal)} label={t("prices.trend")} />
            </div>
            {m.latest ? (
              <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
                <div>
                  <dt className="text-stone-500 dark:text-stone-400">{t("prices.modal")}</dt>
                  <dd className="text-lg font-bold">₹{formatRupees(m.latest.modal, lang)}</dd>
                </div>
                <div>
                  <dt className="text-stone-500 dark:text-stone-400">{t("prices.range")}</dt>
                  <dd>
                    {formatRupees(m.latest.min, lang)}–{formatRupees(m.latest.max, lang)}
                  </dd>
                </div>
                <div>
                  <dt className="text-stone-500 dark:text-stone-400">{t("prices.date")}</dt>
                  <dd>{formatDate(m.latest.date, lang)}</dd>
                </div>
              </dl>
            ) : null}
          </li>
        ))}
      </ul>
      <AlertsPanel crop={crop} district={data?.district ?? district} />
    </div>
  );
}
