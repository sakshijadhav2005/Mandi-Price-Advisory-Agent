import { displayName, formatDate, formatRupees, type PricesResponse } from "@mandi/shared";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertsPanel } from "../components/AlertsPanel";
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
        {data?.markets.map((m) => (
          <li key={m.market} className="card overflow-hidden p-0">
            <div className="flex items-start justify-between gap-3 p-4 pb-3">
              <div className="min-w-0">
                <h3 className="truncate text-lg font-semibold leading-tight">{displayName({ id: m.market, name: m.market_name, names: m.names }, lang)}</h3>
                <span className={`chip mt-1.5 ${STATUS_STYLE[m.status]}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[m.status]}`} aria-hidden />
                  {t(`prices.status.${m.status === "sparse" ? "stale" : m.status}`)}
                  {m.age_days !== null && m.age_days > 0 ? ` · ${t("prices.daysOld", { count: m.age_days })}` : ""}
                </span>
              </div>
              <Sparkline values={m.history.map((h) => h.modal)} label={t("prices.trend")} />
            </div>
            {m.latest ? (
              <dl className="grid grid-cols-[auto_1fr_auto] items-end gap-4 bg-board px-4 py-3 text-sm">
                <div>
                  <dt className="eyebrow text-white/55">{t("prices.modal")}</dt>
                  <dd className="num text-2xl font-semibold leading-none text-board-ink">₹{formatRupees(m.latest.modal, lang)}</dd>
                </div>
                <div>
                  <dt className="eyebrow text-white/55">{t("prices.range")}</dt>
                  <dd className="num whitespace-nowrap text-white/85">
                    {formatRupees(m.latest.min, lang)}–{formatRupees(m.latest.max, lang)}
                  </dd>
                </div>
                <div className="text-right">
                  <dt className="eyebrow text-white/55">{t("prices.date")}</dt>
                  <dd className="num text-white/85">{formatDate(m.latest.date, lang)}</dd>
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
