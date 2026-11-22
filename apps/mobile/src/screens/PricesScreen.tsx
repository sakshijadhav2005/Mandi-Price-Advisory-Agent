import DateTimePicker from "@react-native-community/datetimepicker";
import { PRICE_DAYS, daysBefore, displayName, formatDate, formatRupees, marketOnDay, type MarketPrices, type PriceAlert, type PriceSummary, type PricesResponse } from "@mandi/shared";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Pressable, RefreshControl, ScrollView, Text, TextInput, View } from "react-native";
import { useMobile } from "../context";
import { cacheJson } from "../store";
import { colors, s } from "../theme";

/** yyyy-mm-dd in local time (toISOString would shift the day in India). */
function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

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
  // The last 7 days come in one request (and are cached offline); choosing a day only picks from them.
  const [picked, setPicked] = useState<string | null>(null); // null = today; else a day in the last 7
  const [picking, setPicking] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const res = await cacheJson(`prices7.${district ?? "default"}.${crop}`, () => api.prices(crop, PRICE_DAYS, district, null));
      setData(res.data);
      setCached(res.cached);
    } catch {
      setData(null);
    } finally {
      setRefreshing(false);
    }
    api.alerts().then(setAlerts).catch(() => undefined);
  }, [api, crop, district]);

  const today = data?.as_of ?? isoDay(new Date());
  const firstDay = daysBefore(today, PRICE_DAYS - 1);
  const day = picked && picked >= firstDay && picked < today ? picked : today;
  const allViews = data?.markets.map((m) => ({ m, view: marketOnDay(m, day, today, data.stale_after_days) })) ?? [];
  // Only markets with a real record; empty "no information" cards are left out.
  const views = allViews.filter((v) => v.view.point);
  // The demo banner only when every market shown is on demo prices.
  const withData = data?.markets.filter((m) => m.source) ?? [];
  const allDemo = withData.length > 0 && withData.every((m) => m.source === "synthetic");

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
      {/* Many vegetables: one scrolling strip instead of a block of buttons. */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.row}>
        {(meta?.crops ?? []).map((c) => (
          <Pressable key={c.id} style={crop === c.id ? s.btn : s.btnGhost} onPress={() => setCrop(c.id)} accessibilityState={{ selected: crop === c.id }}>
            <Text style={crop === c.id ? s.btnText : s.btnGhostText}>{displayName(c, lang)}</Text>
          </Pressable>
        ))}
      </ScrollView>
      <Text style={s.small}>{t("prices.unit")}</Text>
      <View style={[s.row, { justifyContent: "space-between", alignItems: "center" }]}>
        <Text style={{ flex: 1, fontSize: 18, fontWeight: "700" }} accessibilityLiveRegion="polite">
          {day === today ? t("prices.todayPrices", { date: formatDate(today, lang) }) : t("prices.pricesFor", { date: formatDate(day, lang) })}
        </Text>
        {day !== today && (
          <Pressable onPress={() => setPicked(null)} accessibilityRole="button" hitSlop={8}>
            <Text style={{ color: colors.leaf, fontWeight: "600" }}>{t("prices.backToToday")}</Text>
          </Pressable>
        )}
        <Pressable style={[s.btnGhost, { minWidth: 48, paddingHorizontal: 0 }]} onPress={() => setPicking(true)} accessibilityRole="button" accessibilityLabel={t("prices.calendar")}>
          <Text style={{ fontSize: 22 }}>📅</Text>
        </Pressable>
      </View>
      {picking && (
        <DateTimePicker
          value={new Date(`${day}T12:00:00`)}
          mode="date"
          minimumDate={new Date(`${firstDay}T00:00:00`)}
          maximumDate={new Date(`${today}T23:59:59`)}
          onChange={(event, chosen) => {
            setPicking(false);
            if (event.type !== "set" || !chosen) return;
            setPicked(isoDay(chosen));
          }}
        />
      )}
      {data && views.length === 0 && (
        <View style={s.banner}>
          <Text style={s.bannerText}>{t("prices.noData")}</Text>
        </View>
      )}
      {cached && (
        <View style={s.banner}>
          <Text style={s.bannerText}>{t("offline.banner")}</Text>
        </View>
      )}
      {allDemo && (
        <View style={s.banner}>
          <Text style={s.bannerText}>{t("prices.demo")}</Text>
        </View>
      )}
      {views.map(({ m, view }) => (
        <View key={m.market} style={s.card}>
          <View style={[s.row, { justifyContent: "space-between" }]}>
            <Text style={s.h2}>{displayName({ id: m.market, name: m.market_name, names: m.names }, lang)}</Text>
            <Text style={{ backgroundColor: STATUS_BG[view.status], paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999, overflow: "hidden", fontSize: 13 }}>
              {t(`prices.status.${view.status === "sparse" ? "stale" : view.status}`)}
            </Text>
          </View>          {view.point && (
            <View style={[s.row, { justifyContent: "space-between" }]}>
              <View>
                <Text style={s.small}>{t("prices.modal")}</Text>
                <Text style={{ fontSize: 20, fontWeight: "700" }}>₹{formatRupees(view.point.modal, lang)}</Text>
              </View>
              <View>
                <Text style={s.small}>{t("prices.range")}</Text>
                <Text>
                  {formatRupees(view.point.min, lang)}–{formatRupees(view.point.max, lang)}
                </Text>
              </View>
              <View>
                <Text style={s.small}>{t("prices.date")}</Text>
                <Text>{formatDate(view.point.date, lang)}</Text>
              </View>
            </View>
          )}
          {view.point && view.point.date !== day && (
            <Text style={[s.small, { color: "#92400e" }]}>{t("prices.lastAvailable", { date: formatDate(view.point.date, lang) })}</Text>
          )}
          <PriceRecords market={m} lang={lang} />
        </View>
      ))}
      {data?.summary && <SummaryCard summary={data.summary} data={data} lang={lang} />}

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

function PriceRecords({ market, lang }: { market: MarketPrices; lang: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  if (market.history.length === 0) return null;
  return (
    <View style={{ gap: 4 }}>
      <Pressable onPress={() => setOpen((o) => !o)} accessibilityRole="button" accessibilityState={{ expanded: open }}>
        <Text style={{ color: colors.leaf, fontWeight: "600", paddingVertical: 6 }}>
          {open ? t("prices.hideRecords") : `${t("prices.records")} (${market.history.length})`}
        </Text>
      </Pressable>
      {open &&
        [...market.history].reverse().map((h) => (
          <View key={h.date} style={[s.row, { justifyContent: "space-between", borderTopWidth: 1, borderTopColor: "#e7e5e4", paddingVertical: 6 }]}>
            <Text style={{ flex: 1 }}>{formatDate(h.date, lang)}</Text>
            <Text style={{ fontWeight: "700", minWidth: 80, textAlign: "right" }}>₹{formatRupees(h.modal, lang)}</Text>
            <Text style={[s.small, { minWidth: 100, textAlign: "right" }]}>
              {formatRupees(h.min, lang)}–{formatRupees(h.max, lang)}
            </Text>
          </View>
        ))}
    </View>
  );
}

function SummaryCard({ summary, data, lang }: { summary: PriceSummary; data: PricesResponse; lang: string }) {
  const { t } = useTranslation();
  const marketName = (id: string) => {
    const m = data.markets.find((x) => x.market === id);
    return m ? displayName({ id: m.market, name: m.market_name, names: m.names }, lang) : id;
  };
  const change = summary.change_pct;
  const cell = { width: "48%" as const, gap: 2 };
  return (
    <View style={s.card}>
      <Text style={s.h2}>{t("prices.summaryTitle")}</Text>
      <Text style={s.small}>
        {formatDate(summary.from, lang)} – {formatDate(summary.to, lang)} · {t("prices.daysWithPrices", { count: summary.days_with_prices })}
      </Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between", rowGap: 12 }}>
        <View style={cell}>
          <Text style={s.small}>{t("prices.lowest")}</Text>
          <Text style={{ fontSize: 18, fontWeight: "700" }}>₹{formatRupees(summary.lowest.modal, lang)}</Text>
          <Text style={s.small}>
            {formatDate(summary.lowest.date, lang)} · {marketName(summary.lowest.market)}
          </Text>
        </View>
        <View style={cell}>
          <Text style={s.small}>{t("prices.highest")}</Text>
          <Text style={{ fontSize: 18, fontWeight: "700" }}>₹{formatRupees(summary.highest.modal, lang)}</Text>
          <Text style={s.small}>
            {formatDate(summary.highest.date, lang)} · {marketName(summary.highest.market)}
          </Text>
        </View>
        <View style={cell}>
          <Text style={s.small}>{t("prices.average")}</Text>
          <Text style={{ fontSize: 18, fontWeight: "700" }}>₹{formatRupees(summary.average, lang)}</Text>
        </View>
        {change !== null && (
          <View style={cell}>
            <Text style={s.small}>{t("prices.change")}</Text>
            <Text style={{ fontSize: 18, fontWeight: "700", color: change > 0 ? colors.leaf : change < 0 ? "#b91c1c" : undefined }}>
              {change > 0 ? "▲" : change < 0 ? "▼" : ""} {Math.abs(change)}%
            </Text>
          </View>
        )}
      </View>
    </View>
  );
}
