import { speechLocale } from "@mandi/i18n";
import { voiceReducer, type ApiClient, type VoiceState } from "@mandi/shared";
import { Audio } from "expo-av";
import * as FileSystem from "expo-file-system";
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
export function useRecorder(api: ApiClient, language: string, consent = false) {
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
      const tr = await api.transcribe(file, language, `speech.${ext}`, consent);
      dispatch({ type: "result", transcript: tr.text, confidence: tr.needs_confirmation ? Math.min(tr.confidence, 0.5) : tr.confidence });
    } catch {
      dispatch({ type: "fail", reason: "failed" });
    }
  }, [api, language, consent]);

  const cancel = useCallback(async () => {
    const recording = rec.current;
    rec.current = null;
    if (recording) await recording.stopAndUnloadAsync().catch(() => undefined);
    dispatch({ type: "cancel" });
  }, []);

  const reset = useCallback(() => dispatch({ type: "reset" }), []);
  return { state, start, stop, cancel, reset };
}

let playing: { sound: Audio.Sound; onDone: () => void } | null = null;

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onloadend = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.readAsDataURL(blob);
  });
}

/** Play the server's voice (e.g. Sarvam AI): clear Marathi and Hindi even on phones without those voices. */
async function speakFromServer(api: ApiClient, text: string, language: string, onDone: () => void): Promise<void> {
  const blob = await api.speak(text, language);
  const uri = `${FileSystem.cacheDirectory}answer-${Date.now()}.mp3`;
  await FileSystem.writeAsStringAsync(uri, await blobToBase64(blob), { encoding: FileSystem.EncodingType.Base64 });
  await Audio.setAudioModeAsync({ allowsRecordingIOS: false, playsInSilentModeIOS: true });
  const { sound } = await Audio.Sound.createAsync({ uri }, { shouldPlay: true });
  playing = { sound, onDone };
  sound.setOnPlaybackStatusUpdate((status) => {
    if (status.isLoaded && status.didJustFinish) finish(sound);
  });
  function finish(s: Audio.Sound) {
    if (playing?.sound !== s) return;
    playing = null;
    void s.unloadAsync();
    void FileSystem.deleteAsync(uri, { idempotent: true });
    onDone();
  }
}

/**
 * Read an answer aloud. With `api` (the server has a voice configured), the server's voice is
 * used; otherwise, or if that fails (offline), the phone's own voice. On the phone, Marathi
 * falls back to a Hindi voice when no Marathi voice is installed.
 */
export async function speak(text: string, language: string, onDone: () => void, api?: ApiClient | null): Promise<void> {
  stopSpeaking();
  if (api) {
    try {
      await speakFromServer(api, text, language, onDone);
      return;
    } catch {
      // fall through to the on-device voice
    }
  }
  let lang = speechLocale(language);
  if (language === "mr") {
    const voices = await Speech.getAvailableVoicesAsync();
    if (!voices.some((v) => v.language.toLowerCase().startsWith("mr"))) lang = "hi-IN";
  }
  Speech.speak(text, { language: lang, rate: 0.95, onDone, onStopped: onDone, onError: onDone });
}

export function stopSpeaking(): void {
  Speech.stop();
  if (playing) {
    const { sound, onDone } = playing;
    playing = null;
    void sound.stopAsync().finally(() => void sound.unloadAsync());
    onDone();
  }
}
