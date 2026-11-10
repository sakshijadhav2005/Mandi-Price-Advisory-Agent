import { displayName, formatDate, formatRupees, type ChatAnswer, type Decision, type Meta } from "@mandi/shared";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../lib/app-context";
import { SpeakerIcon, StopIcon } from "./Icons";

type Answer = Omit<ChatAnswer, "conversation_id" | "message_id">;

const DECISION_STYLE: Record<Decision, string> = {
  sell: "bg-leaf-600 text-white",
  hold: "bg-sky-700 text-white",
  insufficient_data: "bg-amber-200 text-amber-950 dark:bg-amber-300",
};

const CONFIDENCE_DOTS: Record<string, number> = { high: 3, medium: 2, low: 1 };

function marketName(meta: Meta | null, id: string | null | undefined, lang: string) {
  if (!id) return "–";
  return displayName(meta?.markets.find((m) => m.id === id), lang, id);
}

export function AnswerCard({
  answer,
  messageId,
  speaking,
  onSpeak,
  onStop,
  canSpeak,
}: {
  answer: Answer;
  messageId?: number;
  speaking: boolean;
  onSpeak: () => void;
  onStop: () => void;
  canSpeak: boolean;
}) {
  const { t } = useTranslation();
  const { api, meta } = useApp();
  const [open, setOpen] = useState(false);
  const [voted, setVoted] = useState<boolean | null>(null);
  const lang = answer.language;
  const rec = answer.recommendation;
  const isDemo = answer.sources.some((s) => s.kind === "price" && s.origin === "synthetic");

  const vote = async (helpful: boolean) => {
    if (!messageId) return;
    setVoted(helpful);
    try {
      await api.feedback(messageId, helpful);
    } catch {
      setVoted(null);
    }
  };

  return (
    <article className="card space-y-3" lang={lang}>
      {answer.decision && (
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full px-3 py-1 text-base font-bold ${DECISION_STYLE[answer.decision]}`}>
            {t(`answer.decision.${answer.decision}`)}
            {answer.decision === "hold" && rec ? ` · ${rec.horizon_days}d` : ""}
          </span>
          {answer.confidence && answer.decision !== "insufficient_data" && (
            <span className="flex items-center gap-1.5 text-sm text-stone-600 dark:text-stone-300">
              <span className="flex gap-0.5" aria-hidden>
                {[1, 2, 3].map((i) => (
                  <span
                    key={i}
                    className={`h-2.5 w-2.5 rounded-full ${i <= CONFIDENCE_DOTS[answer.confidence!] ? "bg-leaf-600" : "bg-stone-300 dark:bg-stone-700"}`}
                  />
                ))}
              </span>
              {t("answer.confidence", { level: t(`answer.level.${answer.confidence}`) })}
            </span>
          )}
        </div>
      )}

      <p className="whitespace-pre-line text-[17px] leading-relaxed">{answer.text}</p>

      {rec && rec.decision !== "insufficient_data" && rec.best_net_now_per_qtl !== null && (
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <div className="rounded-xl bg-leaf-50 p-3 dark:bg-leaf-900/40">
            <dt className="text-stone-600 dark:text-stone-300">{t("answer.bestMarket")}</dt>
            <dd className="font-semibold">{marketName(meta, rec.best_market_now, lang)}</dd>
            <dd className="text-lg font-bold">{t("answer.perQtl", { value: formatRupees(rec.best_net_now_per_qtl, lang) })}</dd>
            <dd className="text-xs text-stone-500 dark:text-stone-400">{t("answer.netNow")}</dd>
          </div>
          <div className="rounded-xl bg-stone-100 p-3 dark:bg-stone-800">
            <dt className="text-stone-600 dark:text-stone-300">{t("answer.holdFor", { days: rec.horizon_days })}</dt>
            <dd className="font-semibold">{marketName(meta, rec.best_market_hold, lang)}</dd>
            <dd className="text-lg font-bold">{t("answer.perQtl", { value: formatRupees(rec.best_net_hold_per_qtl, lang) })}</dd>
            <dd className="text-xs text-stone-500 dark:text-stone-400">± {formatRupees(rec.uncertainty_per_qtl, lang)}</dd>
          </div>
        </dl>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {canSpeak && (
          <button type="button" className="btn-ghost" onClick={speaking ? onStop : onSpeak}>
            {speaking ? <StopIcon /> : <SpeakerIcon />}
            {speaking ? t("voice.stopPlay") : t("voice.play")}
          </button>
        )}
        <button type="button" className="btn-ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? t("answer.hideSources") : t("answer.showSources")}
        </button>
      </div>

      {open && (
        <div className="space-y-3 border-t border-stone-200 pt-3 text-sm dark:border-stone-800">
          <h3 className="font-semibold">{t("answer.sources")}</h3>
          <ul className="space-y-2">
            {answer.sources.map((s) =>
              s.kind === "price" ? (
                <li key={s.id} className="flex flex-wrap gap-x-2">
                  <span>{t("answer.priceSource", { market: marketName(meta, s.market, lang), date: formatDate(s.date, lang) })}</span>
                  <span className="text-stone-500">({s.origin === "synthetic" ? t("answer.demoData") : s.origin})</span>
                </li>
              ) : (
                <li key={s.id} className="rounded-lg bg-stone-50 p-2 dark:bg-stone-800/60">
                  <p className="font-medium">{s.title}</p>
                  <p className="text-stone-600 dark:text-stone-300">{s.excerpt}…</p>
                  <p className="text-xs text-stone-500">{s.origin}</p>
                </li>
              ),
            )}
          </ul>
          {answer.trace.length > 0 && (
            <>
              <h3 className="font-semibold">{t("answer.steps")}</h3>
              <ol className="list-decimal space-y-0.5 pl-5 font-mono text-xs text-stone-600 dark:text-stone-400">
                {answer.trace.map((step, i) => (
                  <li key={i} className={step.is_error ? "text-red-700 dark:text-red-400" : ""}>
                    {step.tool}: {step.summary}
                  </li>
                ))}
              </ol>
            </>
          )}
          {answer.mode === "offline" && <p className="text-xs text-stone-500">{t("answer.offline")}</p>}
        </div>
      )}

      <aside className="rounded-xl bg-amber-50 p-3 text-sm text-amber-950 dark:bg-amber-950/40 dark:text-amber-100">
        <strong>{t("disclaimerTitle")}:</strong> {answer.disclaimer}
        {isDemo && <span className="mt-1 block font-medium">{t("prices.demo")}</span>}
      </aside>

      {messageId && (
        <div className="flex items-center gap-2 text-sm">
          {voted === null ? (
            <>
              <span className="text-stone-600 dark:text-stone-300">{t("answer.helpful")}</span>
              <button type="button" className="btn-ghost min-h-[40px] px-3" onClick={() => vote(true)}>
                {t("answer.yes")}
              </button>
              <button type="button" className="btn-ghost min-h-[40px] px-3" onClick={() => vote(false)}>
                {t("answer.no")}
              </button>
            </>
          ) : (
            <span className="text-leaf-700 dark:text-leaf-500">{t("answer.thanks")}</span>
          )}
        </div>
      )}
    </article>
  );
}
