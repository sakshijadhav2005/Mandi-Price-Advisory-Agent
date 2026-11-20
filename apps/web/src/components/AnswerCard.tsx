import { displayName, formatDate, formatRupees, type ChatAnswer, type Decision, type Meta } from "@mandi/shared";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useApp } from "../lib/app-context";
import { SpeakerIcon, StopIcon } from "./Icons";

type Answer = Omit<ChatAnswer, "conversation_id" | "message_id">;

const DECISION_STYLE: Record<Decision, string> = {
  sell: "bg-leaf text-white",
  hold: "bg-board text-board-ink",
  insufficient_data: "bg-turmeric-soft text-turmeric-ink ring-1 ring-inset ring-turmeric/40",
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
    <article className="card space-y-4" lang={lang}>
      {answer.decision && (
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <span className={`font-display rounded-lg px-3.5 py-1.5 text-lg font-bold leading-tight tracking-tight ${DECISION_STYLE[answer.decision]}`}>
            {t(`answer.decision.${answer.decision}`)}
            {answer.decision === "hold" && rec ? ` · ${rec.horizon_days}d` : ""}
          </span>
          {answer.confidence && answer.decision !== "insufficient_data" && (
            <span className="flex items-center gap-2 text-sm font-medium text-muted">
              <span className="flex gap-1" aria-hidden>
                {[1, 2, 3].map((i) => (
                  <span key={i} className={`h-1.5 w-5 rounded-full ${i <= CONFIDENCE_DOTS[answer.confidence!] ? "bg-leaf" : "bg-line"}`} />
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
          <div className="rounded-lg bg-board p-3">
            <dt className="text-xs font-medium text-white/65">{t("answer.bestMarket")}</dt>
            <dd className="truncate font-semibold text-white">{marketName(meta, rec.best_market_now, lang)}</dd>
            <dd className="num mt-1 text-xl font-semibold text-board-ink">{t("answer.perQtl", { value: formatRupees(rec.best_net_now_per_qtl, lang) })}</dd>
            <dd className="text-xs text-white/65">{t("answer.netNow")}</dd>
          </div>
          <div className="rounded-lg border border-line bg-sunken p-3">
            <dt className="text-xs font-medium text-muted">{t("answer.holdFor", { days: rec.horizon_days })}</dt>
            <dd className="truncate font-semibold">{marketName(meta, rec.best_market_hold, lang)}</dd>
            <dd className="num mt-1 text-xl font-semibold">{t("answer.perQtl", { value: formatRupees(rec.best_net_hold_per_qtl, lang) })}</dd>
            <dd className="num text-xs text-muted">± {formatRupees(rec.uncertainty_per_qtl, lang)}</dd>
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
        <div className="space-y-3 border-t border-dashed border-line pt-3 text-sm">
          <h3 className="eyebrow">{t("answer.sources")}</h3>
          <ul className="space-y-2">
            {answer.sources.map((s) =>
              s.kind === "price" ? (
                <li key={s.id} className="flex flex-wrap gap-x-2">
                  <span>{t("answer.priceSource", { market: marketName(meta, s.market, lang), date: formatDate(s.date, lang) })}</span>
                  <span className="text-muted">({s.origin === "synthetic" ? t("answer.demoData") : s.origin})</span>
                </li>
              ) : (
                <li key={s.id} className="rounded-lg bg-sunken p-2.5">
                  <p className="font-medium">{s.title}</p>
                  <p className="text-muted">{s.excerpt}…</p>
                  <p className="num mt-1 text-[11px] text-muted">{s.origin}</p>
                </li>
              ),
            )}
          </ul>
          {answer.trace.length > 0 && (
            <>
              <h3 className="eyebrow">{t("answer.steps")}</h3>
              <ol className="list-decimal space-y-0.5 pl-5 font-mono text-xs text-muted">
                {answer.trace.map((step, i) => (
                  <li key={i} className={step.is_error ? "text-chilli-ink" : ""}>
                    {step.tool}: {step.summary}
                  </li>
                ))}
              </ol>
            </>
          )}
          {answer.mode === "offline" && <p className="text-xs text-muted">{t("answer.offline")}</p>}
        </div>
      )}

      <aside className="rounded-r-lg border-l-[3px] border-turmeric bg-turmeric-soft/70 px-3 py-2.5 text-sm text-turmeric-ink">
        <strong>{t("disclaimerTitle")}:</strong> {answer.disclaimer}
        {isDemo && <span className="mt-1 block font-medium">{t("prices.demo")}</span>}
      </aside>

      {messageId && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3 text-sm">
          {voted === null ? (
            <>
              <span className="mr-auto text-muted">{t("answer.helpful")}</span>
              <button type="button" className="btn-ghost min-h-[40px] px-3" onClick={() => vote(true)}>
                {t("answer.yes")}
              </button>
              <button type="button" className="btn-ghost min-h-[40px] px-3" onClick={() => vote(false)}>
                {t("answer.no")}
              </button>
            </>
          ) : (
            <span className="font-medium text-leaf-ink">{t("answer.thanks")}</span>
          )}
        </div>
      )}
    </article>
  );
}
