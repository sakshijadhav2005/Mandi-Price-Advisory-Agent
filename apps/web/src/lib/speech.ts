import { speechLocale } from "@mandi/i18n";
import { voiceReducer, type ApiClient, type VoiceState } from "@mandi/shared";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";

// Minimal typings for the Web Speech API (not in lib.dom for all TS versions).
interface RecognitionAlternative {
  transcript: string;
  confidence: number;
}
interface RecognitionResultEvent {
  results: ArrayLike<ArrayLike<RecognitionAlternative> & { isFinal: boolean }>;
}
interface Recognition {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  continuous: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: RecognitionResultEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
}

function recognitionCtor(): (new () => Recognition) | null {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function browserSttSupported(): boolean {
  return recognitionCtor() !== null;
}

function recorderSupported(): boolean {
  return typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
}

/**
 * Voice input. Prefers the browser recogniser (no cost, no upload); falls back
 * to recording Opus audio and sending it to /voice/transcribe when the server
 * has an STT provider.
 */
export function useVoiceInput(language: string, api: ApiClient, serverStt: boolean, consent = false) {
  const [state, dispatch] = useReducer(voiceReducer, { kind: "idle" } as VoiceState);
  const [interim, setInterim] = useState("");
  const recRef = useRef<Recognition | null>(null);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const cancelled = useRef(false);

  const supported = browserSttSupported() || (serverStt && recorderSupported());

  const start = useCallback(async () => {
    cancelled.current = false;
    setInterim("");
    const Ctor = recognitionCtor();
    if (Ctor) {
      const rec = new Ctor();
      rec.lang = speechLocale(language);
      rec.interimResults = true;
      rec.maxAlternatives = 1;
      rec.continuous = false;
      let finalText = "";
      let confidence = 0;
      rec.onresult = (e) => {
        let text = "";
        for (let i = 0; i < e.results.length; i++) {
          const r = e.results[i];
          text += r[0].transcript;
          if (r.isFinal) {
            finalText = text;
            confidence = r[0].confidence || 0.5; // some engines report 0 when unknown
          }
        }
        setInterim(text);
      };
      rec.onerror = (e) => {
        if (cancelled.current) return;
        dispatch({ type: "fail", reason: e.error === "not-allowed" ? "denied" : e.error === "no-speech" ? "no-speech" : "failed" });
      };
      rec.onend = () => {
        if (cancelled.current) return;
        dispatch({ type: "result", transcript: finalText, confidence });
      };
      recRef.current = rec;
      dispatch({ type: "start", at: Date.now() });
      rec.start();
      return;
    }
    if (serverStt && recorderSupported()) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
        const recorder = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 24000 } : undefined);
        const chunks: Blob[] = [];
        recorder.ondataavailable = (e) => chunks.push(e.data);
        recorder.onstop = async () => {
          stream.getTracks().forEach((t) => t.stop());
          if (cancelled.current) return;
          try {
            const tr = await api.transcribe(new Blob(chunks, { type: recorder.mimeType }), language, "speech.webm", consent);
            dispatch({ type: "result", transcript: tr.text, confidence: tr.needs_confirmation ? Math.min(tr.confidence, 0.5) : tr.confidence });
          } catch {
            dispatch({ type: "fail", reason: "failed" });
          }
        };
        mediaRef.current = recorder;
        dispatch({ type: "start", at: Date.now() });
        recorder.start();
      } catch {
        dispatch({ type: "fail", reason: "denied" });
      }
      return;
    }
    dispatch({ type: "fail", reason: "unsupported" });
  }, [api, language, serverStt, consent]);

  const stop = useCallback(() => {
    dispatch({ type: "stop" });
    recRef.current?.stop();
    if (mediaRef.current?.state === "recording") mediaRef.current.stop();
  }, []);

  const cancel = useCallback(() => {
    cancelled.current = true;
    recRef.current?.abort();
    if (mediaRef.current?.state === "recording") mediaRef.current.stop();
    setInterim("");
    dispatch({ type: "cancel" });
  }, []);

  const reset = useCallback(() => {
    setInterim("");
    dispatch({ type: "reset" });
  }, []);

  useEffect(
    () => () => {
      cancelled.current = true;
      recRef.current?.abort();
      if (mediaRef.current?.state === "recording") mediaRef.current.stop();
    },
    [],
  );

  return { state, interim, supported, start, stop, cancel, reset };
}

// ---------------------------------------------------------------------------- TTS

function pickVoice(lang: string): SpeechSynthesisVoice | undefined {
  const voices = window.speechSynthesis?.getVoices() ?? [];
  const want = speechLocale(lang).toLowerCase();
  return (
    voices.find((v) => v.lang.toLowerCase() === want) ??
    voices.find((v) => v.lang.toLowerCase().startsWith(lang)) ??
    // Marathi voices are often missing; a Hindi voice reads Devanagari acceptably.
    (lang === "mr" ? voices.find((v) => v.lang.toLowerCase().startsWith("hi")) : undefined)
  );
}

export function browserTtsSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function useSpeaker(api: ApiClient, serverTts: boolean) {
  const [speakingId, setSpeakingId] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const stop = useCallback(() => {
    if (browserTtsSupported()) window.speechSynthesis.cancel();
    audioRef.current?.pause();
    setSpeakingId(null);
  }, []);

  const speak = useCallback(
    async (id: number, text: string, lang: string) => {
      stop();
      if (serverTts) {
        try {
          const blob = await api.speak(text, lang);
          const audio = new Audio(URL.createObjectURL(blob));
          audioRef.current = audio;
          audio.onended = () => setSpeakingId(null);
          setSpeakingId(id);
          await audio.play();
          return;
        } catch {
          /* fall through to the browser voice */
        }
      }
      if (!browserTtsSupported()) return;
      const u = new SpeechSynthesisUtterance(text);
      u.lang = speechLocale(lang);
      const voice = pickVoice(lang);
      if (voice) u.voice = voice;
      u.rate = 0.95;
      u.onend = () => setSpeakingId(null);
      u.onerror = () => setSpeakingId(null);
      setSpeakingId(id);
      window.speechSynthesis.speak(u);
    },
    [api, serverTts, stop],
  );

  useEffect(() => stop, [stop]);
  return { speak, stop, speakingId, supported: serverTts || browserTtsSupported() };
}
