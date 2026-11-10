import { StyleSheet } from "react-native";

export const colors = {
  leaf: "#25713a",
  leafDark: "#1d5a2e",
  leafLight: "#f1f8f2",
  sky: "#0369a1",
  amber: "#fde68a",
  amberText: "#451a03",
  bg: "#faf6f1",
  card: "#ffffff",
  border: "#e7e5e4",
  text: "#1c1917",
  muted: "#78716c",
  danger: "#b91c1c",
};

export const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  pad: { padding: 16, gap: 12 },
  h1: { fontSize: 22, fontWeight: "700", color: colors.text },
  h2: { fontSize: 18, fontWeight: "600", color: colors.text },
  body: { fontSize: 17, lineHeight: 26, color: colors.text },
  small: { fontSize: 14, color: colors.muted },
  card: { backgroundColor: colors.card, borderRadius: 16, borderWidth: 1, borderColor: colors.border, padding: 16, gap: 10 },
  btn: { minHeight: 48, borderRadius: 12, paddingHorizontal: 16, alignItems: "center", justifyContent: "center", backgroundColor: colors.leaf },
  btnText: { color: "#fff", fontSize: 16, fontWeight: "600" },
  btnGhost: { minHeight: 48, borderRadius: 12, paddingHorizontal: 16, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: "#d6d3d1", backgroundColor: "#fff" },
  btnGhostText: { color: colors.text, fontSize: 16, fontWeight: "600" },
  input: { minHeight: 48, borderRadius: 12, borderWidth: 1, borderColor: "#d6d3d1", backgroundColor: "#fff", paddingHorizontal: 12, fontSize: 17, color: colors.text },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  banner: { backgroundColor: colors.amber, padding: 10, borderRadius: 12 },
  bannerText: { color: colors.amberText, fontSize: 14 },
});
