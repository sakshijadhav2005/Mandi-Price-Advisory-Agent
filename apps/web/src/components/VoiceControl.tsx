import type { VoiceFailure, VoiceState } from "@mandi/shared";
import { useTranslation } from "react-i18next";
import { MicIcon, SpeakerIcon, StopIcon } from "./Icons";

export function MicButton({
  state,
  supported,
  onStart,
  onStop,
  disabled,
}: {
  state: VoiceState;
  supported: boolean;
  onStart: () => void;
  onStop: () => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const listening = state.kind === "listening";
  return (
    <button
      type="button"
      onClick={listening ? onStop : onStart}
      disabled={disabled || !supported || state.kind === "transcribing"}
      aria-pressed={listening}
      aria-label={listening ? t("voice.stop") : t("voice.start")}
      title={supported ? undefined : t("voice.unsupported")}
      className={`grid h-16 w-16 shrink-0 place-items-center rounded-full text-white shadow-lg transition ${
        listening ? "animate-pulse bg-red-600" : "bg-leaf-600 hover:bg-leaf-700"
      } disabled:bg-stone-400`}
    >
      {listening ? <StopIcon className="h-7 w-7" /> : <MicIcon className="h-8 w-8" />}
    </button>
  );
}

/** Translation key for each way voice input can fail. */
const FAILURE_MESSAGE: Record<VoiceFailure, string> = {
  unsupported: "voice.unsupported",
  insecure: "voice.insecure",
  "no-speech": "voice.failed",
  denied: "voice.denied",
  "no-mic": "voice.noMic",
  network: "voice.network",
  failed: "voice.failed",
};

/**
 * Voice conversation panel: listening (with the live transcript), thinking,
 * speaking the answer, transcript confirmation and error messages.
 */
export function VoicePanel({
  state,
  interim,
  handsFree = false,
  thinking = false,
  speaking = false,
  onEnd,
  onCancel,
  onAccept,
  onEdit,
  onRetry,
}: {
  state: VoiceState;
  interim: string;
  /** A hands-free conversation is running: the panel also shows thinking and speaking. */
  handsFree?: boolean;
  thinking?: boolean;
  speaking?: boolean;
  onEnd?: () => void;
  onCancel: () => void;
  onAccept: (text: string) => void;
  onEdit: (text: string) => void;
  onRetry: () => void;
}) {
  const { t } = useTranslation();
  const listening = state.kind === "listening" || state.kind === "transcribing";
  const phase = listening ? "listening" : handsFree && thinking ? "thinking" : handsFree && speaking ? "speaking" : null;
  if (state.kind === "idle" && !phase) return null;
  return (
    <div className="card space-y-3" role="status" aria-live="polite">
      {phase && (
        <div className="flex flex-col items-center gap-3 py-2 text-center">
          <div className="relative grid h-24 w-24 place-items-center">
            {phase !== "thinking" && (
              <span
                className={`absolute inset-0 animate-ping rounded-full opacity-30 ${phase === "listening" ? "bg-red-500" : "bg-leaf-500"}`}
              />
            )}
            <span
              className={`relative grid h-20 w-20 place-items-center rounded-full text-white shadow-lg ${
                phase === "listening" ? "bg-red-600" : phase === "speaking" ? "bg-leaf-600" : "bg-stone-500"
              }`}
            >
              {phase === "listening" && <MicIcon className="h-9 w-9" />}
              {phase === "speaking" && <SpeakerIcon className="h-9 w-9" />}
              {phase === "thinking" && <span className="h-9 w-9 animate-spin rounded-full border-4 border-white border-t-transparent" />}
            </span>
          </div>
          <p className={`font-semibold ${phase === "listening" ? "text-red-700 dark:text-red-400" : "text-stone-700 dark:text-stone-200"}`}>
            {t(phase === "listening" ? "voice.listening" : phase === "thinking" ? "voice.thinking" : "voice.speaking")}
          </p>
          {phase === "listening" && (interim ? <p className="text-lg">{interim}</p> : <p className="text-sm text-stone-500">{t("voice.hint")}</p>)}
          <div className="flex gap-2">
            {phase === "listening" && !handsFree && (
              <button type="button" className="btn-ghost" onClick={onCancel}>
                {t("voice.cancel")}
              </button>
            )}
            {handsFree && onEnd && (
              <button type="button" className="btn-ghost" onClick={onEnd}>
                {t("voice.end")}
              </button>
            )}
          </div>
        </div>
      )}
      {state.kind === "confirming" && (
        <>
          <p className="text-sm text-stone-600 dark:text-stone-300">{t("voice.confirm")}</p>
          <p className="text-lg font-medium">“{state.transcript}”</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary" onClick={() => onAccept(state.transcript)}>
              {t("voice.sendIt")}
            </button>
            <button type="button" className="btn-ghost" onClick={() => onEdit(state.transcript)}>
              {t("voice.retype")}
            </button>
            <button type="button" className="btn-ghost" onClick={onRetry}>
              {t("voice.speakAgain")}
            </button>
          </div>
        </>
      )}
      {state.kind === "error" && (
        <>
          <p>{t(FAILURE_MESSAGE[state.reason])}</p>
          <div className="flex gap-2">
            {state.reason !== "unsupported" && state.reason !== "insecure" && (
              <button type="button" className="btn-primary" onClick={onRetry}>
                {t("voice.speakAgain")}
              </button>
            )}
            <button type="button" className="btn-ghost" onClick={onCancel}>
              {t("voice.cancel")}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
