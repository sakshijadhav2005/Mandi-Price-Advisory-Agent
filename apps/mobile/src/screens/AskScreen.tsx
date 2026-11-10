import { assistantTurn, canAutoSend, turnsFromConversation, userTurn, type Turn } from "@mandi/shared";
import * as Location from "expo-location";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { AnswerCard } from "../components/AnswerCard";
import { useMobile } from "../context";
import { colors, s } from "../theme";
import { speak, stopSpeaking, useRecorder } from "../voice";


export function AskScreen({ conversationId: initialId }: { conversationId: number | null }) {
  const { t } = useTranslation();
  const { api, meta, language, autoSpeak, district, keepRecordings } = useMobile();
  const lang = language ?? "en";
  const [conversationId, setConversationId] = useState<number | null>(initialId);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [speakingKey, setSpeakingKey] = useState<number | null>(null);
  const [coords, setCoords] = useState<{ lat: number; lon: number } | null>(null);
  const scroll = useRef<ScrollView>(null);
  const voice = useRecorder(api, lang, keepRecordings && !!meta?.voice.stores_recordings);
  const serverStt = !!meta?.voice.server_stt;

  useEffect(() => {
    if (!initialId) return;
    api
      .conversation(initialId)
      .then((c) => setTurns(turnsFromConversation(c)))
      .catch(() => undefined);
  }, [api, initialId]);

  const toggleSpeak = useCallback((key: number, text: string, l: string) => {
    if (speakingKey === key) {
      stopSpeaking();
      setSpeakingKey(null);
      return;
    }
    setSpeakingKey(key);
    void speak(text, l, () => setSpeakingKey((k) => (k === key ? null : k)));
  }, [speakingKey]);

  const send = useCallback(
    async (text: string, mode: "text" | "voice" = "text") => {
      const message = text.trim();
      if (!message || busy) return;
      setInput("");
      setError(null);
      setTurns((ts) => [...ts, userTurn(message)]);
      setBusy(true);
      try {
        const res = await api.chat({ message, language: lang, conversation_id: conversationId, lat: coords?.lat, lon: coords?.lon, input_mode: mode, district });
        setConversationId(res.conversation_id);
        const turn = assistantTurn(res, res.message_id);
        const key = turn.key;
        setTurns((ts) => [...ts, turn]);
        if (autoSpeak || mode === "voice") {
          setSpeakingKey(key);
          void speak(res.text, res.language, () => setSpeakingKey((k) => (k === key ? null : k)));
        }
      } catch {
        setError(t("ask.error"));
      } finally {
        setBusy(false);
      }
    },
    [api, autoSpeak, busy, conversationId, coords, district, lang, t],
  );

  useEffect(() => {
    if (voice.state.kind === "confirming" && canAutoSend(voice.state)) {
      const text = voice.state.transcript;
      voice.reset();
      void send(text, "voice");
    }
  }, [voice, send]);

  const shareLocation = async () => {
    const perm = await Location.requestForegroundPermissionsAsync();
    if (!perm.granted) return;
    const pos = await Location.getLastKnownPositionAsync() ?? (await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Low }));
    if (pos) setCoords({ lat: pos.coords.latitude, lon: pos.coords.longitude });
  };

  const listening = voice.state.kind === "listening";
  const examples = t("ask.examples", { returnObjects: true }) as string[];

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView ref={scroll} contentContainerStyle={s.pad} onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: true })}>
        {turns.length === 0 && (
          <View style={{ gap: 8 }}>
            <Text style={s.body}>{t("ask.empty")}</Text>
            {examples.map((ex) => (
              <Pressable key={ex} style={[s.btnGhost, { alignItems: "flex-start" }]} onPress={() => void send(ex)}>
                <Text style={{ fontSize: 16, color: colors.text }}>{ex}</Text>
              </Pressable>
            ))}
          </View>
        )}
        {turns.map((turn) =>
          turn.role === "user" ? (
            <View key={turn.key} style={{ alignSelf: "flex-end", maxWidth: "85%", backgroundColor: colors.leaf, borderRadius: 16, paddingHorizontal: 14, paddingVertical: 8 }}>
              <Text style={{ color: "#fff", fontSize: 17 }}>{turn.text}</Text>
            </View>
          ) : (
            <AnswerCard
              key={turn.key}
              answer={turn.answer}
              messageId={turn.messageId}
              speaking={speakingKey === turn.key}
              onSpeak={() => toggleSpeak(turn.key, turn.answer.text, turn.answer.language)}
            />
          ),
        )}
        {busy && (
          <View style={[s.card, s.row]}>
            <ActivityIndicator color={colors.leaf} />
            <Text style={s.body}>{t("ask.thinking")}</Text>
          </View>
        )}
        {error && <Text style={{ color: colors.danger }}>{error}</Text>}

        {voice.state.kind === "confirming" && (
          <View style={s.card}>
            <Text style={s.small}>{t("voice.confirm")}</Text>
            <Text style={[s.body, { fontWeight: "600" }]}>“{voice.state.transcript}”</Text>
            <View style={s.row}>
              <Pressable style={s.btn} onPress={() => { const tx = (voice.state as { transcript: string }).transcript; voice.reset(); void send(tx, "voice"); }}>
                <Text style={s.btnText}>{t("voice.sendIt")}</Text>
              </Pressable>
              <Pressable style={s.btnGhost} onPress={() => { setInput((voice.state as { transcript: string }).transcript); voice.reset(); }}>
                <Text style={s.btnGhostText}>{t("voice.retype")}</Text>
              </Pressable>
            </View>
          </View>
        )}
        {voice.state.kind === "error" && (
          <View style={s.banner}>
            <Text style={s.bannerText}>{t("voice.failed")}</Text>
          </View>
        )}
      </ScrollView>

      <View style={{ padding: 12, gap: 8, borderTopWidth: 1, borderColor: colors.border, backgroundColor: colors.card }}>
        {!serverStt && <Text style={s.small}>{t("voice.unsupported")}</Text>}
        <View style={s.row}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={listening ? t("voice.stop") : t("voice.start")}
            disabled={!serverStt || busy || voice.state.kind === "transcribing"}
            onPress={() => (listening ? void voice.stop() : void voice.start())}
            style={{ width: 64, height: 64, borderRadius: 32, alignItems: "center", justifyContent: "center", backgroundColor: !serverStt ? "#a8a29e" : listening ? colors.danger : colors.leaf }}
          >
            {voice.state.kind === "transcribing" ? <ActivityIndicator color="#fff" /> : <Text style={{ color: "#fff", fontSize: 26 }}>{listening ? "■" : "🎤"}</Text>}
          </Pressable>
          <TextInput
            style={[s.input, { flex: 1 }]}
            value={input}
            onChangeText={setInput}
            placeholder={t("ask.placeholder")}
            multiline
            onSubmitEditing={() => void send(input)}
          />
          <Pressable style={[s.btn, { width: 64, height: 64 }]} disabled={busy || !input.trim()} onPress={() => void send(input)} accessibilityLabel={t("ask.send")}>
            <Text style={s.btnText}>➤</Text>
          </Pressable>
        </View>
        <Pressable onPress={() => void shareLocation()}>
          <Text style={{ color: colors.leaf, fontSize: 14 }}>📍 {coords ? t("ask.locationOn") : t("ask.useLocation")}</Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}
