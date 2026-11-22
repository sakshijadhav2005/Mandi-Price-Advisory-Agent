import { assistantTurn, canAutoSend, displayName, turnsFromConversation, userTurn } from "@mandi/shared";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useNavigate } from "react-router-dom";
import { AnswerCard } from "../components/AnswerCard";
import { PinIcon, SendIcon } from "../components/Icons";
import { MicButton, VoicePanel } from "../components/VoiceControl";
import { useApp } from "../lib/app-context";
import { getChat, resetChat, setChat, useChat } from "../lib/chat-session";
import { useSpeaker, useVoiceInput } from "../lib/speech";


export function AskPage() {
  const { t } = useTranslation();
  const { api, meta, language, autoSpeak, district, keepRecordings } = useApp();
  const lang = language ?? "en";
  const params = useParams();
  const navigate = useNavigate();
  // The conversation lives outside the page (lib/chat-session), so switching tabs while an
  // answer is loading neither loses the question nor the answer.
  const { turns, busy, error, crop, qty } = useChat();
  const setCrop = (v: string) => setChat({ crop: v });
  const setQty = (v: string) => setChat({ qty: v });
  const [input, setInput] = useState("");
  const [coords, setCoords] = useState<{ lat: number; lon: number } | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // Hands-free voice conversation: tap the mic once, then speak, hear the
  // answer, and speak again without touching the screen.
  const [handsFree, setHandsFree] = useState(false);
  const wasSpeaking = useRef(false);

  const voice = useVoiceInput(lang, api, !!meta?.voice.server_stt, keepRecordings && !!meta?.voice.stores_recordings);
  const speaker = useSpeaker(api, !!meta?.voice.server_tts);

  // Load an existing conversation from history.
  useEffect(() => {
    if (!params.id) return;
    const id = Number(params.id);
    const current = getChat();
    if (current.conversationId === id && (current.busy || current.turns.length > 0)) return; // already open
    resetChat();
    const session = getChat().session;
    api
      .conversation(id)
      .then((c) => {
        if (getChat().session === session) setChat({ conversationId: c.id, turns: turnsFromConversation(c) });
      })
      .catch(() => navigate("/", { replace: true }));
  }, [api, params.id, navigate]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, busy]);

  const send = useCallback(
    async (text: string, mode: "text" | "voice" = "text") => {
      const message = text.trim();
      const start = getChat();
      if (!message || start.busy) return;
      const session = start.session;
      setInput("");
      setChat((s) => ({ error: null, busy: true, turns: [...s.turns, userTurn(message)] }));
      try {
        const res = await api.chat({
          message,
          language: lang,
          crop: crop || null,
          quantity_qtl: qty ? Number(qty) : null,
          lat: coords?.lat ?? null,
          lon: coords?.lon ?? null,
          conversation_id: start.conversationId,
          input_mode: mode,
          district,
        });
        if (getChat().session !== session) return; // "new chat" or logout meanwhile
        const turn = assistantTurn(res, res.message_id);
        setChat((s) => ({ conversationId: res.conversation_id, turns: [...s.turns, turn] }));
        // Read aloud only if the farmer is still on this page.
        if (mounted.current && (autoSpeak || mode === "voice")) void speaker.speak(turn.key, res.text, res.language);
      } catch {
        if (getChat().session === session) setChat({ error: navigator.onLine ? t("ask.error") : t("offline.noAnswer") });
      } finally {
        if (getChat().session === session) setChat({ busy: false });
      }
    },
    [api, autoSpeak, coords, crop, district, lang, qty, speaker, t],
  );

  const startVoice = useCallback(() => {
    speaker.stop(); // tapping the mic while the answer is read aloud interrupts it
    setHandsFree(true);
    void voice.start();
  }, [speaker, voice]);

  const endVoice = useCallback(() => {
    setHandsFree(false);
    speaker.stop();
    voice.cancel();
  }, [speaker, voice]);

  // In the hands-free conversation every transcript is sent straight away and
  // shown as the question bubble. Otherwise only confident results are sent and
  // the rest wait for confirmation. While an answer is still loading the
  // transcript stays on screen instead of being dropped.
  useEffect(() => {
    if (!busy && voice.state.kind === "confirming" && (handsFree || canAutoSend(voice.state))) {
      const text = voice.state.transcript;
      voice.reset();
      void send(text, "voice");
    }
  }, [busy, handsFree, voice, send]);

  // A voice error or a failed answer ends the hands-free conversation.
  useEffect(() => {
    if (voice.state.kind === "error" || error) setHandsFree(false);
  }, [voice.state.kind, error]);

  // When the spoken answer finishes, listen for the next question.
  useEffect(() => {
    const speaking = speaker.speakingId !== null;
    if (wasSpeaking.current && !speaking && handsFree && !busy && voice.state.kind === "idle") {
      void voice.start();
    }
    wasSpeaking.current = speaking;
  }, [speaker.speakingId, handsFree, busy, voice]);

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
    endVoice();
    resetChat();
    navigate("/");
  };

  const examples = t("ask.examples", { returnObjects: true }) as string[];

  return (
    <div className="space-y-4">
      {turns.length === 0 ? (
        <section className="space-y-4">
          <p className="font-display text-2xl font-semibold leading-snug tracking-tight">{t("ask.empty")}</p>
          <ol className="overflow-hidden rounded-xl border border-line bg-surface">
            {examples.map((ex, i) => (
              <li key={ex} className="border-line [&:not(:first-child)]:border-t">
                <button
                  type="button"
                  className="group flex min-h-[56px] w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-sunken"
                  onClick={() => void send(ex)}
                >
                  <span className="num w-6 shrink-0 text-xs font-semibold text-muted" aria-hidden>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="flex-1">{ex}</span>
                  <span className="text-muted transition-transform group-hover:translate-x-0.5" aria-hidden>
                    →
                  </span>
                </button>
              </li>
            ))}
          </ol>
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
              <p className="max-w-[85%] rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-paper">{turn.text}</p>
            </li>
          ) : (
            <li key={turn.key}>
              <AnswerCard
                answer={turn.answer}
                messageId={turn.messageId}
                canSpeak={speaker.supported}
                speaking={speaker.speakingId === turn.key}
                onSpeak={() => void speaker.speak(turn.key, turn.answer.text, turn.answer.language)}
                onStop={() => {
                  setHandsFree(false);
                  speaker.stop();
                }}
              />
            </li>
          ),
        )}
        {busy && !handsFree && (
          <li className="card flex items-center gap-3 text-muted">
            <span className="flex items-end gap-1" aria-hidden>
              {[0, 150, 300].map((d) => (
                <span key={d} className="h-3 w-1.5 animate-pulse rounded-full bg-turmeric" style={{ animationDelay: `${d}ms` }} />
              ))}
            </span>
            {t("ask.thinking")}
          </li>
        )}
      </ol>
      {error && (
        <p role="alert" className="rounded-r-lg border-l-[3px] border-chilli bg-chilli-soft px-3 py-2.5 text-chilli-ink">
          {error}
        </p>
      )}

      <VoicePanel
        state={voice.state}
        interim={voice.interim}
        handsFree={handsFree}
        thinking={busy}
        speaking={speaker.speakingId !== null}
        onEnd={endVoice}
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

      <form onSubmit={onSubmit} className="card space-y-3 shadow-[0_8px_24px_-12px_rgb(var(--ink)/0.25)]">
        <div className="flex items-end gap-3">
          <MicButton state={voice.state} supported={voice.supported} onStart={startVoice} onStop={voice.stop} disabled={busy} />
          <label className="sr-only" htmlFor="question">
            {t("ask.placeholder")}
          </label>
          <textarea
            id="question"
            ref={inputRef}
            className="input min-h-[64px] flex-1 resize-none py-2.5"
            rows={2}
            autoComplete="off"
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
        {!voice.supported && <p className="text-sm text-muted">{t("voice.unsupported")}</p>}
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
            <input id="qty" className="input num" inputMode="decimal" autoComplete="off" value={qty} onChange={(e) => setQty(e.target.value.replace(/[^\d.]/g, ""))} />
          </div>
        </div>
        <button type="button" className="flex min-h-[44px] items-center gap-1.5 text-sm font-semibold text-leaf-ink" onClick={shareLocation}>
          <PinIcon />
          {coords ? t("ask.locationOn") : t("ask.useLocation")}
        </button>
      </form>
      <div ref={bottomRef} />
    </div>
  );
}
