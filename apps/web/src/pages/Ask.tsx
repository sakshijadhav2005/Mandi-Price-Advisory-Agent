import { assistantTurn, canAutoSend, displayName, turnsFromConversation, userTurn, type Turn } from "@mandi/shared";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useNavigate } from "react-router-dom";
import { AnswerCard } from "../components/AnswerCard";
import { PinIcon, SendIcon } from "../components/Icons";
import { MicButton, VoicePanel } from "../components/VoiceControl";
import { useApp } from "../lib/app-context";
import { useSpeaker, useVoiceInput } from "../lib/speech";


export function AskPage() {
  const { t } = useTranslation();
  const { api, meta, language, autoSpeak, district, keepRecordings } = useApp();
  const lang = language ?? "en";
  const params = useParams();
  const navigate = useNavigate();
  const [conversationId, setConversationId] = useState<number | null>(params.id ? Number(params.id) : null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [crop, setCrop] = useState<string>("");
  const [qty, setQty] = useState<string>("");
  const [coords, setCoords] = useState<{ lat: number; lon: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const voice = useVoiceInput(lang, api, !!meta?.voice.server_stt, keepRecordings && !!meta?.voice.stores_recordings);
  const speaker = useSpeaker(api, !!meta?.voice.server_tts);

  // Load an existing conversation from history.
  useEffect(() => {
    if (!params.id) return;
    api
      .conversation(Number(params.id))
      .then((c) => {
        setConversationId(c.id);
        setTurns(turnsFromConversation(c));
      })
      .catch(() => navigate("/", { replace: true }));
  }, [api, params.id, navigate]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, busy]);

  const send = useCallback(
    async (text: string, mode: "text" | "voice" = "text") => {
      const message = text.trim();
      if (!message || busy) return;
      setError(null);
      setInput("");
      setTurns((ts) => [...ts, userTurn(message)]);
      setBusy(true);
      try {
        const res = await api.chat({
          message,
          language: lang,
          crop: crop || null,
          quantity_qtl: qty ? Number(qty) : null,
          lat: coords?.lat ?? null,
          lon: coords?.lon ?? null,
          conversation_id: conversationId,
          input_mode: mode,
          district,
        });
        setConversationId(res.conversation_id);
        const turn = assistantTurn(res, res.message_id);
        setTurns((ts) => [...ts, turn]);
        if (autoSpeak || mode === "voice") void speaker.speak(turn.key, res.text, res.language);
      } catch {
        setError(navigator.onLine ? t("ask.error") : t("offline.noAnswer"));
      } finally {
        setBusy(false);
      }
    },
    [api, autoSpeak, busy, conversationId, coords, crop, district, lang, qty, speaker, t],
  );

  // Confident voice results are sent straight away; others wait for confirmation.
  useEffect(() => {
    if (voice.state.kind === "confirming" && canAutoSend(voice.state)) {
      const text = voice.state.transcript;
      voice.reset();
      void send(text, "voice");
    }
  }, [voice, send]);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void send(input);
  };

  const shareLocation = () => {
    navigator.geolocation?.getCurrentPosition(
      (p) => setCoords({ lat: p.coords.latitude, lon: p.coords.longitude }),
      () => setCoords(null),
      { maximumAge: 3600_000, timeout: 10_000 },
    );
  };

  const newChat = () => {
    speaker.stop();
    setTurns([]);
    setConversationId(null);
    navigate("/");
  };

  const examples = t("ask.examples", { returnObjects: true }) as string[];

  return (
    <div className="space-y-4">
      {turns.length === 0 ? (
        <section className="space-y-3">
          <p className="text-stone-700 dark:text-stone-300">{t("ask.empty")}</p>
          <div className="flex flex-col gap-2">
            {examples.map((ex) => (
              <button key={ex} type="button" className="btn-ghost justify-start text-left font-normal" onClick={() => void send(ex)}>
                {ex}
              </button>
            ))}
          </div>
        </section>
      ) : (
        <div className="flex justify-end">
          <button type="button" className="btn-ghost min-h-[44px] px-3 text-sm" onClick={newChat}>
            {t("ask.newChat")}
          </button>
        </div>
      )}

      <ol className="space-y-3" aria-live="polite">
        {turns.map((turn) =>
          turn.role === "user" ? (
            <li key={turn.key} className="flex justify-end">
              <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-leaf-600 px-4 py-2 text-white">{turn.text}</p>
            </li>
          ) : (
            <li key={turn.key}>
              <AnswerCard
                answer={turn.answer}
                messageId={turn.messageId}
                canSpeak={speaker.supported}
                speaking={speaker.speakingId === turn.key}
                onSpeak={() => void speaker.speak(turn.key, turn.answer.text, turn.answer.language)}
                onStop={speaker.stop}
              />
            </li>
          ),
        )}
        {busy && (
          <li className="card flex items-center gap-3 text-stone-600 dark:text-stone-300">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-leaf-600 border-t-transparent" />
            {t("ask.thinking")}
          </li>
        )}
      </ol>
      {error && <p className="rounded-xl bg-red-50 p-3 text-red-800 dark:bg-red-950/50 dark:text-red-200">{error}</p>}

      <VoicePanel
        state={voice.state}
        interim={voice.interim}
        onCancel={voice.cancel}
        onAccept={(text) => {
          voice.reset();
          void send(text, "voice");
        }}
        onEdit={(text) => {
          voice.reset();
          setInput(text);
          inputRef.current?.focus();
        }}
        onRetry={() => void voice.start()}
      />

      <form onSubmit={onSubmit} className="card space-y-3">
        <div className="flex items-end gap-3">
          <MicButton state={voice.state} supported={voice.supported} onStart={() => void voice.start()} onStop={voice.stop} disabled={busy} />
          <label className="sr-only" htmlFor="question">
            {t("ask.placeholder")}
          </label>
          <textarea
            id="question"
            ref={inputRef}
            className="input min-h-[64px] flex-1 resize-none py-2"
            rows={2}
            value={input}
            placeholder={t("ask.placeholder")}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(input);
              }
            }}
          />
          <button type="submit" className="btn-primary h-16 w-16 shrink-0 p-0" disabled={busy || !input.trim()} aria-label={t("ask.send")}>
            <SendIcon className="h-6 w-6" />
          </button>
        </div>
        {!voice.supported && <p className="text-sm text-stone-500">{t("voice.unsupported")}</p>}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="crop">
              {t("ask.crop")}
            </label>
            <select id="crop" className="input" value={crop} onChange={(e) => setCrop(e.target.value)}>
              <option value="">{t("ask.anyCrop")}</option>
              {meta?.crops.map((c) => (
                <option key={c.id} value={c.id}>
                  {displayName(c, lang)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="qty">
              {t("ask.quantity")}
            </label>
            <input id="qty" className="input" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value.replace(/[^\d.]/g, ""))} />
          </div>
        </div>
        <button type="button" className="flex min-h-[44px] items-center gap-1.5 text-sm text-leaf-700 dark:text-leaf-500" onClick={shareLocation}>
          <PinIcon />
          {coords ? t("ask.locationOn") : t("ask.useLocation")}
        </button>
      </form>
      <div ref={bottomRef} />
    </div>
  );
}
