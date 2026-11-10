import { displayName, formatDate, formatRupees, type AppNotification, type PriceAlert } from "@mandi/shared";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../lib/app-context";

/** Price alerts for one crop, plus the in-app inbox of triggered alerts. */
export function AlertsPanel({ crop, district }: { crop: string; district?: string | null }) {
  const { t } = useTranslation();
  const { api, meta, language } = useApp();
  const lang = language ?? "en";
  const [alerts, setAlerts] = useState<PriceAlert[]>([]);
  const [inbox, setInbox] = useState<AppNotification[]>([]);
  const [market, setMarket] = useState("");
  const [direction, setDirection] = useState<"above" | "below">("above");
  const [threshold, setThreshold] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.alerts().then(setAlerts).catch(() => setAlerts([]));
    api.notifications(true).then(setInbox).catch(() => setInbox([]));
  }, [api]);

  useEffect(load, [load]);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.createAlert({ crop, market: market || null, district: district ?? null, direction, threshold: Number(threshold), language: lang });
      setThreshold("");
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const remove = async (id: number) => {
    await api.deleteAlert(id);
    load();
  };

  const markRead = async () => {
    await api.markNotificationsRead();
    setInbox([]);
  };

  const cropName = (id: string) => displayName(meta?.crops.find((c) => c.id === id), lang, id);
  const marketName = (id: string | null) => (id ? displayName(meta?.markets.find((m) => m.id === id), lang, id) : t("alerts.anyMarket"));
  const mine = alerts.filter((a) => a.active && a.crop === crop);

  return (
    <section className="space-y-3">
      {inbox.length > 0 && (
        <div className="card space-y-2 border-leaf-500" role="status">
          <h3 className="font-semibold">{t("alerts.inbox")}</h3>
          <ul className="space-y-2">
            {inbox.map((n) => (
              <li key={n.id} className="rounded-xl bg-leaf-50 p-3 text-sm dark:bg-leaf-900/40">
                <p className="font-semibold">{n.title}</p>
                <p>{n.body}</p>
              </li>
            ))}
          </ul>
          <button type="button" className="btn-ghost" onClick={() => void markRead()}>
            {t("alerts.markRead")}
          </button>
        </div>
      )}

      <div className="card space-y-3">
        <h3 className="text-lg font-semibold">{t("alerts.title")}</h3>
        {mine.length === 0 ? (
          <p className="text-sm text-stone-600 dark:text-stone-300">{t("alerts.none")}</p>
        ) : (
          <ul className="space-y-2">
            {mine.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-2 text-sm">
                <span>
                  {t("alerts.item", {
                    crop: cropName(a.crop),
                    market: marketName(a.market),
                    direction: t(`alerts.${a.direction}`),
                    price: formatRupees(a.threshold, lang),
                  })}
                  {a.last_triggered_on && <span className="block text-xs text-stone-500">{t("alerts.lastHit", { date: formatDate(a.last_triggered_on, lang) })}</span>}
                </span>
                <button type="button" className="btn-ghost min-h-[40px] px-3" onClick={() => void remove(a.id)}>
                  {t("alerts.delete")}
                </button>
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={add} className="grid grid-cols-2 gap-2">
          <select className="input col-span-2" aria-label={t("prices.market")} value={market} onChange={(e) => setMarket(e.target.value)}>
            <option value="">{t("alerts.anyMarket")}</option>
            {meta?.markets.filter((m) => !district || !m.district || m.district === district).map((m) => (
              <option key={m.id} value={m.id}>
                {displayName(m, lang)}
              </option>
            ))}
          </select>
          <select className="input" aria-label={t("alerts.above")} value={direction} onChange={(e) => setDirection(e.target.value as "above" | "below")}>
            <option value="above">{t("alerts.above")}</option>
            <option value="below">{t("alerts.below")}</option>
          </select>
          <input
            className="input"
            inputMode="numeric"
            placeholder={t("alerts.threshold")}
            aria-label={t("alerts.threshold")}
            value={threshold}
            onChange={(e) => setThreshold(e.target.value.replace(/\D/g, ""))}
          />
          <button type="submit" className="btn-primary col-span-2" disabled={!threshold}>
            {t("alerts.add")}
          </button>
        </form>
        {error && <p className="text-sm text-red-700 dark:text-red-400">{error}</p>}
        <p className="text-xs text-stone-500">{t("alerts.pushNote")}</p>
      </div>
    </section>
  );
}
