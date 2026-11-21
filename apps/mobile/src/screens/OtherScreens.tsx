import { LANGUAGES, resources, type LanguageCode } from "@mandi/i18n";
import { displayName, type ConversationSummary, type DistrictInfo } from "@mandi/shared";
import { useEffect, useMemo, useState } from "react";
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
  const { api, meta, language, setLanguage, autoSpeak, setAutoSpeak, keepRecordings, setKeepRecordings, apiBase, setApiBase, district, setDistrict, loggedIn, logout, chooseGuest } = useMobile();
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
        <DistrictPicker districts={meta.districts} states={meta.states} value={district ?? meta.districts[0].id} onChange={setDistrict} lang={language ?? "en"} />
      )}
      <View style={s.card}>
        <Text style={s.h2}>{t("alerts.title")}</Text>
        <Pressable style={s.btn} onPress={() => void registerForPush(api, language ?? "en").then(setPushOk)}>
          <Text style={s.btnText}>🔔 {t("alerts.title")}</Text>
        </Pressable>
        {pushOk !== null && <Text style={s.small}>{pushOk ? "✓" : "✗"}</Text>}
      </View>
      <View style={s.card}>
        {loggedIn ? (
          <Pressable
            style={s.btnGhost}
            onPress={() => {
              logout();
              chooseGuest(false);
            }}
          >
            <Text style={s.btnGhostText}>{t("login.logout")}</Text>
          </Pressable>
        ) : (
          <Pressable style={s.btn} onPress={() => chooseGuest(false)}>
            <Text style={s.btnText}>{t("auth.signIn")}</Text>
          </Pressable>
        )}
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

/** State first (a scrolling strip), then that state's districts: India has ~790 districts. */
function DistrictPicker({
  districts,
  states,
  value,
  onChange,
  lang,
}: {
  districts: DistrictInfo[];
  states?: string[];
  value: string;
  onChange: (id: string) => void;
  lang: string;
}) {
  const { t } = useTranslation();
  const current = districts.find((d) => d.id === value) ?? districts[0]!;
  const [state, setState] = useState(current.state);
  useEffect(() => setState(current.state), [current.state]);
  const allStates = useMemo(() => states ?? [...new Set(districts.map((d) => d.state))].sort(), [states, districts]);
  const inState = useMemo(
    () => districts.filter((d) => d.state === state).sort((a, b) => displayName(a, lang).localeCompare(displayName(b, lang))),
    [districts, state, lang],
  );
  return (
    <View style={s.card}>
      <Text style={s.h2}>{t("settings.state")}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.row}>
        {allStates.map((st) => (
          <Pressable key={st} style={st === state ? s.btn : s.btnGhost} onPress={() => setState(st)} accessibilityState={{ selected: st === state }}>
            <Text style={st === state ? s.btnText : s.btnGhostText}>{st}</Text>
          </Pressable>
        ))}
      </ScrollView>
      <Text style={s.h2}>{t("settings.district")}</Text>
      <Text style={s.small}>{t("settings.districtHelp")}</Text>
      <View style={[s.row, { flexWrap: "wrap" }]}>
        {inState.map((d) => (
          <Pressable key={d.id} style={[d.id === value ? s.btn : s.btnGhost, { flexGrow: 1 }]} onPress={() => onChange(d.id)} accessibilityState={{ selected: d.id === value }}>
            <Text style={d.id === value ? s.btnText : s.btnGhostText}>{displayName(d, lang)}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}
