import { displayName, formatDate, formatRupees, type PriceAlert, type PricesResponse } from "@mandi/shared";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Pressable, RefreshControl, ScrollView, Text, TextInput, View } from "react-native";
import { useMobile } from "../context";
import { cacheJson } from "../store";
import { colors, s } from "../theme";

const STATUS_BG = { fresh: "#dcefdf", stale: "#fef3c7", missing: "#e7e5e4", sparse: "#fef3c7" } as const;

export function PricesScreen() {
  const { t } = useTranslation();
  const { api, meta, language, district } = useMobile();
  const lang = language ?? "en";
  const [crop, setCrop] = useState("onion");
  const [data, setData] = useState<PricesResponse | null>(null);
  const [cached, setCached] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [alerts, setAlerts] = useState<PriceAlert[]>([]);
  const [threshold, setThreshold] = useState("");
  const [direction, setDirection] = useState<"above" | "below">("above");

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const res = await cacheJson(`prices.${district ?? "default"}.${crop}`, () => api.prices(crop, 30, district));
      setData(res.data);
      setCached(res.cached);
    } catch {
      setData(null);
    } finally {
      setRefreshing(false);
    }
    api.alerts().then(setAlerts).catch(() => undefined);
  }, [api, crop, district]);

  useEffect(() => {
    void load();
  }, [load]);

  const addAlert = async () => {
    await api.createAlert({ crop, market: null, district: data?.district ?? district, direction, threshold: Number(threshold), language: lang }).catch(() => undefined);
    setThreshold("");
    void load();
  };

  const mine = alerts.filter((a) => a.active && a.crop === crop);

  return (
    <ScrollView contentContainerStyle={s.pad} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => void load()} />}>
      <Text style={s.h1}>{t("prices.title")}</Text>
      <View style={s.row}>
        {(meta?.crops ?? []).map((c) => (
          <Pressable key={c.id} style={crop === c.id ? s.btn : s.btnGhost} onPress={() => setCrop(c.id)}>
            <Text style={crop === c.id ? s.btnText : s.btnGhostText}>{displayName(c, lang)}</Text>
          </Pressable>
        ))}
      </View>
      <Text style={s.small}>{t("prices.unit")}</Text>
      {cached && (
        <View style={s.banner}>
          <Text style={s.bannerText}>{t("offline.banner")}</Text>
        </View>
      )}
      {data?.markets.some((m) => m.source === "synthetic") && (
        <View style={s.banner}>
          <Text style={s.bannerText}>{t("prices.demo")}</Text>
        </View>
      )}
      {data?.markets.map((m) => (
        <View key={m.market} style={s.card}>
          <View style={[s.row, { justifyContent: "space-between" }]}>
            <Text style={s.h2}>{displayName({ id: m.market, name: m.market_name, names: m.names }, lang)}</Text>
            <Text style={{ backgroundColor: STATUS_BG[m.status], paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999, overflow: "hidden", fontSize: 13 }}>
              {t(`prices.status.${m.status === "sparse" ? "stale" : m.status}`)}
            </Text>
          </View>
          {m.latest && (
            <View style={[s.row, { justifyContent: "space-between" }]}>
              <View>
                <Text style={s.small}>{t("prices.modal")}</Text>
                <Text style={{ fontSize: 20, fontWeight: "700" }}>₹{formatRupees(m.latest.modal, lang)}</Text>
              </View>
              <View>
                <Text style={s.small}>{t("prices.range")}</Text>
                <Text>
                  {formatRupees(m.latest.min, lang)}–{formatRupees(m.latest.max, lang)}
                </Text>
              </View>
              <View>
                <Text style={s.small}>{t("prices.date")}</Text>
                <Text>{formatDate(m.latest.date, lang)}</Text>
              </View>
            </View>
          )}
        </View>
      ))}

      <View style={s.card}>
        <Text style={s.h2}>{t("alerts.title")}</Text>
        {mine.length === 0 && <Text style={s.small}>{t("alerts.none")}</Text>}
        {mine.map((a) => (
          <View key={a.id} style={[s.row, { justifyContent: "space-between" }]}>
            <Text style={{ flex: 1 }}>
              {t("alerts.item", { crop: displayName(meta?.crops.find((c) => c.id === a.crop), lang, a.crop), market: t("alerts.anyMarket"), direction: t(`alerts.${a.direction}`), price: formatRupees(a.threshold, lang) })}
            </Text>
            <Pressable style={[s.btnGhost, { minHeight: 40 }]} onPress={() => void api.deleteAlert(a.id).then(load)}>
              <Text style={s.btnGhostText}>{t("alerts.delete")}</Text>
            </Pressable>
          </View>
        ))}
        <View style={s.row}>
          {(["above", "below"] as const).map((d) => (
            <Pressable key={d} style={[direction === d ? s.btn : s.btnGhost, { flex: 1 }]} onPress={() => setDirection(d)}>
              <Text style={direction === d ? s.btnText : s.btnGhostText}>{t(`alerts.${d}`)}</Text>
            </Pressable>
          ))}
        </View>
        <TextInput style={s.input} keyboardType="number-pad" placeholder={t("alerts.threshold")} value={threshold} onChangeText={(v) => setThreshold(v.replace(/\D/g, ""))} />
        <Pressable style={[s.btn, !threshold && { backgroundColor: colors.muted }]} disabled={!threshold} onPress={() => void addAlert()}>
          <Text style={s.btnText}>{t("alerts.add")}</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}
