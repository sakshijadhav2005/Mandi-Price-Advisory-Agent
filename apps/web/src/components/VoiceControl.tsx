import type { VoiceState } from "@mandi/shared";
import { useTranslation } from "react-i18next";
import { MicIcon, StopIcon } from "./Icons";

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

/** Recording indicator, transcript confirmation and error messages. */
export function VoicePanel({
  state,
  interim,
  onCancel,
  onAccept,
  onEdit,
  onRetry,
}: {
  state: VoiceState;
  interim: string;
  onCancel: () => void;
  onAccept: (text: string) => void;
  onEdit: (text: string) => void;
  onRetry: () => void;
}) {
  const { t } = useTranslation();
  if (state.kind === "idle") return null;
  return (
    <div className="card space-y-3" role="status" aria-live="polite">
      {(state.kind === "listening" || state.kind === "transcribing") && (
        <>
          <div className="flex items-center gap-2 font-semibold text-red-700 dark:text-red-400">
            <span className="h-3 w-3 animate-pulse rounded-full bg-red-600" />
            {t("voice.listening")}
          </div>
          {interim && <p className="text-lg">{interim}</p>}
          <button type="button" className="btn-ghost" onClick={onCancel}>
            {t("voice.cancel")}
          </button>
        </>
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
          <p>{state.reason === "unsupported" ? t("voice.unsupported") : t("voice.failed")}</p>
          <div className="flex gap-2">
            {state.reason !== "unsupported" && (
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
