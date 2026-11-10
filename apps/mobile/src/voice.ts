import { speechLocale } from "@mandi/i18n";
import { voiceReducer, type ApiClient, type VoiceState } from "@mandi/shared";
import { Audio } from "expo-av";
import * as Speech from "expo-speech";
import { useCallback, useReducer, useRef } from "react";

/** Small mono AAC recording (~4 KB/s), good enough for speech and cheap on mobile data. */
const RECORDING: Audio.RecordingOptions = {
  isMeteringEnabled: false,
  android: {
    extension: ".m4a",
    outputFormat: Audio.AndroidOutputFormat.MPEG_4,
    audioEncoder: Audio.AndroidAudioEncoder.AAC,
    sampleRate: 16000,
    numberOfChannels: 1,
    bitRate: 32000,
  },
  ios: {
    extension: ".m4a",
    outputFormat: Audio.IOSOutputFormat.MPEG4AAC,
    audioQuality: Audio.IOSAudioQuality.MEDIUM,
    sampleRate: 16000,
    numberOfChannels: 1,
    bitRate: 32000,
  },
  web: { mimeType: "audio/webm", bitsPerSecond: 24000 },
};

/**
 * Record on the device and transcribe on the server (/voice/transcribe).
 * Needs STT_PROVIDER=whisper on the backend; otherwise the screen offers typing.
 */
export function useRecorder(api: ApiClient, language: string) {
  const [state, dispatch] = useReducer(voiceReducer, { kind: "idle" } as VoiceState);
  const rec = useRef<Audio.Recording | null>(null);

  const start = useCallback(async () => {
    const perm = await Audio.requestPermissionsAsync();
    if (!perm.granted) {
      dispatch({ type: "fail", reason: "denied" });
      return;
    }
    await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });
    try {
      const { recording } = await Audio.Recording.createAsync(RECORDING);
      rec.current = recording;
      dispatch({ type: "start", at: Date.now() });
    } catch {
      dispatch({ type: "fail", reason: "failed" });
    }
  }, []);

  const stop = useCallback(async () => {
    const recording = rec.current;
    if (!recording) return;
    dispatch({ type: "stop" });
    rec.current = null;
    try {
      await recording.stopAndUnloadAsync();
      await Audio.setAudioModeAsync({ allowsRecordingIOS: false });
      const uri = recording.getURI();
      if (!uri) throw new Error("no recording");
      const ext = uri.split(".").pop() ?? "m4a";
      // React Native's FormData accepts { uri, name, type } file parts.
      const file = { uri, name: `speech.${ext}`, type: ext === "m4a" ? "audio/mp4" : "audio/webm" } as unknown as Blob;
      const tr = await api.transcribe(file, language, `speech.${ext}`);
      dispatch({ type: "result", transcript: tr.text, confidence: tr.needs_confirmation ? Math.min(tr.confidence, 0.5) : tr.confidence });
    } catch {
      dispatch({ type: "fail", reason: "failed" });
    }
  }, [api, language]);

  const cancel = useCallback(async () => {
    const recording = rec.current;
    rec.current = null;
    if (recording) await recording.stopAndUnloadAsync().catch(() => undefined);
    dispatch({ type: "cancel" });
  }, []);

  const reset = useCallback(() => dispatch({ type: "reset" }), []);
  return { state, start, stop, cancel, reset };
}

/** On-device text-to-speech. Falls back to a Hindi voice for Marathi when none is installed. */
export async function speak(text: string, language: string, onDone: () => void): Promise<void> {
  Speech.stop();
  let lang = speechLocale(language);
  if (language === "mr") {
    const voices = await Speech.getAvailableVoicesAsync();
    if (!voices.some((v) => v.language.toLowerCase().startsWith("mr"))) lang = "hi-IN";
  }
  Speech.speak(text, { language: lang, rate: 0.95, onDone, onStopped: onDone, onError: onDone });
}

export function stopSpeaking(): void {
  Speech.stop();
}
