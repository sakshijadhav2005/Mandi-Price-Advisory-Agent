import { StatusBar } from "expo-status-bar";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { MobileProvider, useMobile } from "./src/context";
import { AskScreen } from "./src/screens/AskScreen";
import { HistoryScreen, LanguageScreen, SettingsScreen } from "./src/screens/OtherScreens";
import { PricesScreen } from "./src/screens/PricesScreen";
import { store } from "./src/store";
import { colors, s } from "./src/theme";

type Tab = "ask" | "prices" | "history" | "settings";
const TABS: { id: Tab; icon: string }[] = [
  { id: "ask", icon: "💬" },
  { id: "prices", icon: "📈" },
  { id: "history", icon: "🕘" },
  { id: "settings", icon: "⚙️" },
];

function Shell() {
  const { t } = useTranslation();
  const { language } = useMobile();
  const [tab, setTab] = useState<Tab>("ask");
  const [conversation, setConversation] = useState<{ id: number | null; nonce: number }>({ id: null, nonce: 0 });

  if (!language) return <LanguageScreen />;

  return (
    <View style={{ flex: 1 }}>
      <View style={[s.row, { padding: 12, borderBottomWidth: 1, borderColor: colors.border }]}>
        <View style={{ width: 36, height: 36, borderRadius: 10, backgroundColor: colors.leaf, alignItems: "center", justifyContent: "center" }}>
          <Text style={{ color: "#fff", fontWeight: "700", fontSize: 18 }}>₹</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: 18, fontWeight: "700" }}>{t("app.name")}</Text>
          <Text style={s.small} numberOfLines={1}>
            {t("app.tagline")}
          </Text>
        </View>
        {tab === "ask" && (
          <Pressable onPress={() => setConversation((c) => ({ id: null, nonce: c.nonce + 1 }))}>
            <Text style={{ color: colors.leaf, fontWeight: "600" }}>{t("ask.newChat")}</Text>
          </Pressable>
        )}
      </View>
      <View style={{ flex: 1 }}>
        {tab === "ask" && <AskScreen key={`${conversation.id}-${conversation.nonce}`} conversationId={conversation.id} />}
        {tab === "prices" && <PricesScreen />}
        {tab === "history" && (
          <HistoryScreen
            onOpen={(id) => {
              setConversation((c) => ({ id, nonce: c.nonce + 1 }));
              setTab("ask");
            }}
          />
        )}
        {tab === "settings" && <SettingsScreen />}
      </View>
      <View style={{ flexDirection: "row", borderTopWidth: 1, borderColor: colors.border, backgroundColor: colors.card }}>
        {TABS.map(({ id, icon }) => (
          <Pressable key={id} onPress={() => setTab(id)} style={{ flex: 1, minHeight: 60, alignItems: "center", justifyContent: "center" }} accessibilityRole="tab" accessibilityState={{ selected: tab === id }}>
            <Text style={{ fontSize: 20 }}>{icon}</Text>
            <Text style={{ fontSize: 12, fontWeight: "600", color: tab === id ? colors.leaf : colors.muted }}>{t(`nav.${id}`)}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

export default function App() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    store.hydrate().finally(() => setReady(true));
  }, []);
  return (
    <SafeAreaProvider>
      <SafeAreaView style={s.screen}>
        <StatusBar style="dark" />
        {ready ? (
          <MobileProvider>
            <Shell />
          </MobileProvider>
        ) : (
          <ActivityIndicator style={{ flex: 1 }} color={colors.leaf} />
        )}
      </SafeAreaView>
    </SafeAreaProvider>
  );
}
