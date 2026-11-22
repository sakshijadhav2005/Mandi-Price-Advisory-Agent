import { ApiError, type AdminContent, type AdminDocument } from "@mandi/shared";
import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useMobile } from "../context";
import { colors, s } from "../theme";

/*
 * Staff-only screen (English): sign in with the server's ADMIN_TOKEN, see what the advisory
 * features still need, and approve / reject storage documents. Uploading documents is on
 * the web admin page (/admin). The token is kept only while this screen is open.
 */

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 404) return "Admin is turned off on this server (set ADMIN_TOKEN in the backend .env).";
    if (e.status === 401) return "Wrong admin token.";
    return e.message;
  }
  return "Could not reach the server.";
}

export function AdminScreen({ onClose }: { onClose: () => void }) {
  const { api } = useMobile();
  const [input, setInput] = useState("");
  const [token, setToken] = useState("");
  const [content, setContent] = useState<AdminContent | null>(null);
  const [docs, setDocs] = useState<AdminDocument[]>([]);
  const [reviewer, setReviewer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (t: string) => {
      setBusy(true);
      setError(null);
      try {
        const [c, d] = await Promise.all([api.adminContent(t), api.adminDocuments(t)]);
        setContent(c);
        setDocs(d);
        setToken(t);
      } catch (e) {
        setContent(null);
        setToken("");
        setError(errorText(e));
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  const decide = async (doc: AdminDocument, decision: "approve" | "reject") => {
    setError(null);
    try {
      await api.reviewDocument(token, doc.id, decision, reviewer.trim());
      await load(token);
    } catch (e) {
      setError(errorText(e));
    }
  };

  const header = (
    <View style={[s.row, { justifyContent: "space-between" }]}>
      <Text style={s.h1}>Admin</Text>
      <Pressable onPress={onClose} accessibilityRole="button" style={[s.btnGhost, { minHeight: 40 }]}>
        <Text style={s.btnGhostText}>Close</Text>
      </Pressable>
    </View>
  );

  if (!content) {
    return (
      <ScrollView contentContainerStyle={s.pad}>
        {header}
        <View style={s.card}>
          <Text style={s.small}>Admin token (ADMIN_TOKEN from the backend .env)</Text>
          <TextInput style={s.input} value={input} onChangeText={setInput} secureTextEntry autoCapitalize="none" accessibilityLabel="Admin token" />
          {error && <Text style={{ color: colors.danger }}>{error}</Text>}
          <Pressable style={[s.btn, (!input.trim() || busy) && { opacity: 0.5 }]} disabled={!input.trim() || busy} onPress={() => void load(input.trim())}>
            {busy ? <ActivityIndicator color="#fff" /> : <Text style={s.btnText}>Sign in</Text>}
          </Pressable>
        </View>
      </ScrollView>
    );
  }

  const pending = content.pesticide_rows.pending ?? 0;
  const bulletin = content.agromet[0];
  return (
    <ScrollView contentContainerStyle={s.pad}>
      {header}
      <View style={s.card}>
        <Text style={s.h2}>Advisory content</Text>
        <Text style={s.body}>Pesticide rows to review: {pending}</Text>
        <Text style={s.body}>Pesticide rows approved: {content.pesticide_rows.approved ?? 0}</Text>
        <Text style={s.body}>Documents approved: {content.documents.approved ?? 0}</Text>
        <Text style={s.body}>KCC answers: {content.kcc_answers}</Text>
        <Text style={s.body}>
          IMD bulletin: {bulletin ? `${bulletin.district}, issued ${bulletin.issued_on}, valid till ${bulletin.valid_until}` : "none stored yet"}
        </Text>
        <Text style={s.body}>
          Schemes: {content.schemes.total} entries, {content.schemes.needs_attention.length} need attention
        </Text>
        {content.schemes.needs_attention.map((line) => (
          <Text key={line} style={s.small}>
            • {line}
          </Text>
        ))}
      </View>
      <View style={s.card}>
        <Text style={s.h2}>{docs.length} storage documents</Text>
        <Text style={s.small}>Add documents on the web admin page (/admin). Approve them here once checked.</Text>
        <TextInput style={s.input} value={reviewer} onChangeText={setReviewer} placeholder="Your name (recorded)" accessibilityLabel="Reviewer name" />
        {error && <Text style={{ color: colors.danger }}>{error}</Text>}
        {docs.map((d) => (
          <View key={d.id} style={{ borderTopWidth: 1, borderColor: colors.border, paddingTop: 10, gap: 6 }}>
            <Text style={{ fontWeight: "700", color: colors.text }}>{d.title}</Text>
            <Text style={s.small}>
              {d.publisher} · {d.crop} · {d.language} · {d.passages} passages · {d.status}
              {d.reviewed_by ? ` · ${d.reviewed_by}` : ""}
            </Text>
            <View style={s.row}>
              {d.status !== "approved" && (
                <Pressable style={[s.btn, { flex: 1 }, !reviewer.trim() && { opacity: 0.5 }]} disabled={!reviewer.trim()} onPress={() => void decide(d, "approve")}>
                  <Text style={s.btnText}>Approve</Text>
                </Pressable>
              )}
              {d.status !== "rejected" && (
                <Pressable style={[s.btnGhost, { flex: 1 }, !reviewer.trim() && { opacity: 0.5 }]} disabled={!reviewer.trim()} onPress={() => void decide(d, "reject")}>
                  <Text style={s.btnGhostText}>Reject</Text>
                </Pressable>
              )}
            </View>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}
