import { LANGUAGES, resources, type LanguageCode } from "@mandi/i18n";
import { displayName, type ConversationSummary } from "@mandi/shared";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";
import { useMobile } from "../context";
import { registerForPush } from "../push";
import { colors, s } from "../theme";

export function LanguageScreen() {
  const { setLanguage } = useMobile();
  return (
    <ScrollView contentContainerStyle={[s.pad, { flexGrow: 1, justifyContent: "center" }]}>
      {LANGUAGES.map((l) => (
        <Text key={l.code} style={[s.h2, { textAlign: "center" }]}>
          {resources[l.code].translation.language.choose}
        </Text>
      ))}
      {LANGUAGES.map((l) => (
        <Pressable key={l.code} style={[s.btn, { minHeight: 60 }]} onPress={() => setLanguage(l.code as LanguageCode)}>
          <Text style={[s.btnText, { fontSize: 20 }]}>
            {l.label}
            {l.code !== "en" ? `  (${l.english})` : ""}
          </Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}

export function HistoryScreen({ onOpen }: { onOpen: (id: number) => void }) {
  const { t } = useTranslation();
  const { api } = useMobile();
  const [items, setItems] = useState<ConversationSummary[] | null>(null);

  useEffect(() => {
    api.conversations().then(setItems).catch(() => setItems([]));
  }, [api]);

  return (
    <ScrollView contentContainerStyle={s.pad}>
      <Text style={s.h1}>{t("history.title")}</Text>
      {items?.length === 0 && <Text style={s.body}>{t("history.empty")}</Text>}
      {items?.map((c) => (
        <View key={c.id} style={[s.card, s.row]}>
          <Pressable style={{ flex: 1 }} onPress={() => onOpen(c.id)}>
            <Text style={{ fontSize: 16, fontWeight: "600" }} numberOfLines={1}>
              {c.title}
            </Text>
            <Text style={s.small}>
              {new Date(c.created_at).toLocaleDateString()} · {t("history.messages", { count: c.messages })}
            </Text>
          </Pressable>
          <Pressable
            style={[s.btnGhost, { minHeight: 40 }]}
            onPress={() => void api.deleteConversation(c.id).then(() => setItems((xs) => xs?.filter((x) => x.id !== c.id) ?? null))}
          >
            <Text style={s.btnGhostText}>{t("history.delete")}</Text>
          </Pressable>
        </View>
      ))}
    </ScrollView>
  );
}

export function SettingsScreen() {
  const { t } = useTranslation();
  const { api, meta, language, setLanguage, autoSpeak, setAutoSpeak, keepRecordings, setKeepRecordings, apiBase, setApiBase, district, setDistrict } = useMobile();
  const [server, setServer] = useState(apiBase);
  const [pushOk, setPushOk] = useState<boolean | null>(null);

  return (
    <ScrollView contentContainerStyle={s.pad}>
      <Text style={s.h1}>{t("settings.title")}</Text>
      <View style={s.card}>
        <Text style={s.h2}>{t("settings.language")}</Text>
        <View style={s.row}>
          {LANGUAGES.map((l) => (
            <Pressable key={l.code} style={[language === l.code ? s.btn : s.btnGhost, { flex: 1 }]} onPress={() => setLanguage(l.code as LanguageCode)}>
              <Text style={language === l.code ? s.btnText : s.btnGhostText}>{l.label}</Text>
            </Pressable>
          ))}
        </View>
        <View style={[s.row, { justifyContent: "space-between" }]}>
          <Text style={[s.body, { flex: 1 }]}>{t("settings.speakAnswers")}</Text>
          <Switch value={autoSpeak} onValueChange={setAutoSpeak} trackColor={{ true: colors.leaf }} />
        </View>
        {meta?.voice.server_stt && meta.voice.stores_recordings && (
          <View style={[s.row, { justifyContent: "space-between" }]}>
            <View style={{ flex: 1 }}>
              <Text style={s.body}>{t("settings.keepRecordings")}</Text>
              <Text style={s.small}>{t("settings.keepRecordingsHelp")}</Text>
            </View>
            <Switch value={keepRecordings} onValueChange={setKeepRecordings} trackColor={{ true: colors.leaf }} />
          </View>
        )}
      </View>
      {meta?.districts && meta.districts.length > 1 && (
        <View style={s.card}>
          <Text style={s.h2}>{t("settings.district")}</Text>
          <View style={[s.row, { flexWrap: "wrap" }]}>
            {meta.districts.map((d) => {
              const active = (district ?? meta.districts![0].id) === d.id;
              return (
                <Pressable key={d.id} style={[active ? s.btn : s.btnGhost, { flexGrow: 1 }]} onPress={() => setDistrict(d.id)}>
                  <Text style={active ? s.btnText : s.btnGhostText}>{displayName(d, language ?? "en")}</Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      )}
      <View style={s.card}>
        <Text style={s.h2}>{t("alerts.title")}</Text>
        <Pressable style={s.btn} onPress={() => void registerForPush(api, language ?? "en").then(setPushOk)}>
          <Text style={s.btnText}>🔔 {t("alerts.title")}</Text>
        </Pressable>
        {pushOk !== null && <Text style={s.small}>{pushOk ? "✓" : "✗"}</Text>}
      </View>
      <View style={s.card}>
        <Text style={s.small}>{t("settings.server")}</Text>
        <TextInput style={s.input} value={server} onChangeText={setServer} autoCapitalize="none" keyboardType="url" />
        <Pressable style={s.btnGhost} onPress={() => setApiBase(server.trim())}>
          <Text style={s.btnGhostText}>OK</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}
