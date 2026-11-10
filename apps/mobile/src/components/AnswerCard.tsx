import { displayName, formatDate, formatRupees, type ChatAnswer, type Decision } from "@mandi/shared";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Pressable, Text, View } from "react-native";
import { useMobile } from "../context";
import { colors, s } from "../theme";

type Answer = Omit<ChatAnswer, "conversation_id" | "message_id">;

const BADGE: Record<Decision, { bg: string; fg: string }> = {
  sell: { bg: colors.leaf, fg: "#fff" },
  hold: { bg: colors.sky, fg: "#fff" },
  insufficient_data: { bg: colors.amber, fg: colors.amberText },
};

export function AnswerCard({
  answer,
  messageId,
  speaking,
  onSpeak,
}: {
  answer: Answer;
  messageId?: number;
  speaking: boolean;
  onSpeak: () => void;
}) {
  const { t } = useTranslation();
  const { api, meta } = useMobile();
  const [open, setOpen] = useState(false);
  const [voted, setVoted] = useState(false);
  const lang = answer.language;
  const rec = answer.recommendation;
  const market = (id: string | null | undefined) => (id ? displayName(meta?.markets.find((m) => m.id === id), lang, id) : "–");

  return (
    <View style={s.card}>
      {answer.decision && (
        <View style={s.row}>
          <Text style={{ backgroundColor: BADGE[answer.decision].bg, color: BADGE[answer.decision].fg, fontWeight: "700", fontSize: 16, paddingHorizontal: 12, paddingVertical: 4, borderRadius: 999, overflow: "hidden" }}>
            {t(`answer.decision.${answer.decision}`)}
          </Text>
          {answer.confidence && answer.decision !== "insufficient_data" && (
            <Text style={s.small}>{t("answer.confidence", { level: t(`answer.level.${answer.confidence}`) })}</Text>
          )}
        </View>
      )}
      <Text style={s.body}>{answer.text}</Text>

      {rec && rec.decision !== "insufficient_data" && rec.best_net_now_per_qtl !== null && (
        <View style={[s.row, { alignItems: "stretch" }]}>
          <View style={{ flex: 1, backgroundColor: colors.leafLight, borderRadius: 12, padding: 10 }}>
            <Text style={s.small}>{t("answer.bestMarket")}</Text>
            <Text style={{ fontWeight: "600" }}>{market(rec.best_market_now)}</Text>
            <Text style={{ fontSize: 18, fontWeight: "700" }}>{t("answer.perQtl", { value: formatRupees(rec.best_net_now_per_qtl, lang) })}</Text>
          </View>
          <View style={{ flex: 1, backgroundColor: "#f5f5f4", borderRadius: 12, padding: 10 }}>
            <Text style={s.small}>{t("answer.holdFor", { days: rec.horizon_days })}</Text>
            <Text style={{ fontWeight: "600" }}>{market(rec.best_market_hold)}</Text>
            <Text style={{ fontSize: 18, fontWeight: "700" }}>{t("answer.perQtl", { value: formatRupees(rec.best_net_hold_per_qtl, lang) })}</Text>
          </View>
        </View>
      )}

      <View style={s.row}>
        <Pressable style={s.btnGhost} onPress={onSpeak} accessibilityRole="button">
          <Text style={s.btnGhostText}>{speaking ? t("voice.stopPlay") : t("voice.play")}</Text>
        </Pressable>
        <Pressable style={s.btnGhost} onPress={() => setOpen((o) => !o)} accessibilityRole="button">
          <Text style={s.btnGhostText}>{open ? t("answer.hideSources") : t("answer.sources")}</Text>
        </Pressable>
      </View>

      {open && (
        <View style={{ gap: 6 }}>
          {answer.sources.map((src) =>
            src.kind === "price" ? (
              <Text key={src.id} style={s.small}>
                {t("answer.priceSource", { market: market(src.market), date: formatDate(src.date, lang) })}
                {src.origin === "synthetic" ? ` (${t("answer.demoData")})` : ""}
              </Text>
            ) : (
              <View key={src.id} style={{ backgroundColor: "#fafaf9", borderRadius: 8, padding: 8 }}>
                <Text style={{ fontWeight: "600" }}>{src.title}</Text>
                <Text style={s.small}>{src.excerpt}…</Text>
              </View>
            ),
          )}
        </View>
      )}

      <View style={s.banner}>
        <Text style={s.bannerText}>
          {t("disclaimerTitle")}: {answer.disclaimer}
        </Text>
      </View>

      {messageId !== undefined &&
        (voted ? (
          <Text style={{ color: colors.leaf }}>{t("answer.thanks")}</Text>
        ) : (
          <View style={s.row}>
            <Text style={s.small}>{t("answer.helpful")}</Text>
            {[true, false].map((helpful) => (
              <Pressable
                key={String(helpful)}
                style={[s.btnGhost, { minHeight: 40 }]}
                onPress={() => {
                  setVoted(true);
                  void api.feedback(messageId, helpful).catch(() => setVoted(false));
                }}
              >
                <Text style={s.btnGhostText}>{helpful ? t("answer.yes") : t("answer.no")}</Text>
              </Pressable>
            ))}
          </View>
        ))}
    </View>
  );
}
