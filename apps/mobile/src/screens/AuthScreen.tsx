import { LANGUAGES, type LanguageCode } from "@mandi/i18n";
import { ApiError } from "@mandi/shared";
import Constants from "expo-constants";
import * as Google from "expo-auth-session/providers/google";
import * as WebBrowser from "expo-web-browser";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
} from "react-native";
import { useMobile } from "../context";
import { colors, s } from "../theme";

// Closes the browser tab Google sign-in opened once it redirects back to the app.
WebBrowser.maybeCompleteAuthSession();

const extra = (Constants.expoConfig?.extra ?? {}) as { googleAndroidClientId?: string; googleIosClientId?: string };
/** The OAuth client ID for this platform (Android / iOS client types in Google Cloud Console). */
const NATIVE_GOOGLE_ID = (Platform.OS === "ios" ? extra.googleIosClientId : extra.googleAndroidClientId) || "";

/*
 * Sign in / sign up, in the app's own colours (cream background, white card,
 * leaf-green buttons, amber accent). Phone-code (OTP) sign-in stays available for farmers
 * without an email address.
 */

/** Only colours from the app theme (src/theme.ts), so this screen matches the rest of the app. */
const c = {
  bg: colors.bg,
  card: colors.card,
  cardEdge: colors.border,
  field: "#fff",
  fieldEdge: "#d6d3d1", // same edge as s.input
  fieldFocus: colors.leaf,
  accent: colors.leaf,
  accentStrong: colors.leafDark,
  text: colors.text,
  muted: colors.muted,
  placeholder: colors.muted,
  primary: colors.leaf,
  primaryText: "#fff",
  amber: colors.amber,
  amberText: colors.amberText,
  errorBg: colors.card,
  errorEdge: colors.danger,
  errorText: colors.danger,
};

function Field({ label, icon, trailing, ...input }: { label: string; icon: string; trailing?: ReactNode } & TextInputProps) {
  const [focused, setFocused] = useState(false);
  return (
    <View style={{ gap: 6 }}>
      <Text style={st.label}>{label}</Text>
      <View style={[st.field, focused && { borderColor: c.fieldFocus }, input.editable === false && { opacity: 0.6 }]}>
        <Text style={st.fieldIcon} accessibilityElementsHidden importantForAccessibility="no">
          {icon}
        </Text>
        <TextInput
          {...input}
          accessibilityLabel={label}
          placeholderTextColor={c.placeholder}
          style={[st.input, input.style]}
          onFocus={(e) => {
            setFocused(true);
            input.onFocus?.(e);
          }}
          onBlur={(e) => {
            setFocused(false);
            input.onBlur?.(e);
          }}
        />
        {trailing}
      </View>
    </View>
  );
}

function PasswordField({ label, placeholder, value, onChangeText, isNew }: { label: string; placeholder: string; value: string; onChangeText: (v: string) => void; isNew?: boolean }) {
  const { t } = useTranslation();
  const [show, setShow] = useState(false);
  return (
    <Field
      label={label}
      icon="🔒"
      placeholder={placeholder}
      value={value}
      onChangeText={onChangeText}
      secureTextEntry={!show}
      autoCapitalize="none"
      autoCorrect={false}
      autoComplete={isNew ? "new-password" : "current-password"}
      textContentType={isNew ? "newPassword" : "password"}
      trailing={
        <Pressable onPress={() => setShow((v) => !v)} hitSlop={8} style={st.eye} accessibilityRole="button" accessibilityLabel={show ? t("auth.hidePassword") : t("auth.showPassword")}>
          <Text style={{ fontSize: 18 }}>{show ? "🙈" : "👁️"}</Text>
        </Pressable>
      }
    />
  );
}

function PrimaryButton({ label, onPress, disabled, busy, leading, trailing, accent }: { label: string; onPress: () => void; disabled?: boolean; busy?: boolean; leading?: string; trailing?: string; accent?: boolean }) {
  const textStyle = [st.primaryText, accent && { color: c.amberText }];
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || busy}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!(disabled || busy), busy: !!busy }}
      style={({ pressed }) => [st.primary, accent && st.accentBtn, (disabled || busy) && { opacity: 0.55 }, pressed && { transform: [{ translateY: 1 }], opacity: 0.9 }]}
    >
      {busy ? (
        <ActivityIndicator color={accent ? c.amberText : c.primaryText} />
      ) : (
        <>
          {leading ? <Text style={textStyle}>{leading}</Text> : null}
          <Text style={textStyle}>{label}</Text>
          {trailing ? <Text style={textStyle}>{trailing}</Text> : null}
        </>
      )}
    </Pressable>
  );
}

function Divider({ label }: { label: string }) {
  return (
    <View style={st.divider}>
      <View style={st.rule} />
      <Text style={{ color: c.muted, fontSize: 14 }}>{label}</Text>
      <View style={st.rule} />
    </View>
  );
}

/** English / हिंदी / मराठी, the same setting as in Settings (saved, switches the whole app). */
function LanguageSwitch() {
  const { language, setLanguage } = useMobile();
  return (
    <View style={st.langRow} accessibilityRole="radiogroup" accessibilityLabel="Language / भाषा">
      {LANGUAGES.map((l) => {
        const on = language === l.code;
        return (
          <Pressable
            key={l.code}
            onPress={() => setLanguage(l.code as LanguageCode)}
            accessibilityRole="radio"
            accessibilityState={{ checked: on }}
            style={[st.langBtn, on && st.langBtnOn]}
          >
            <Text style={[st.langText, on && { color: c.accentStrong }]}>{l.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function Header({ icon, title, subtitle }: { icon: string; title: string; subtitle: string }) {
  return (
    <View style={{ alignItems: "center", marginBottom: 20 }}>
      <View style={st.logo}>
        <Text style={{ fontSize: icon === "₹" ? 30 : 28, color: "#fff", fontWeight: "700" }}>{icon}</Text>
      </View>
      <Text style={st.title}>{title}</Text>
      <Text style={st.subtitle}>{subtitle}</Text>
    </View>
  );
}

function ErrorText({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <View style={st.error} accessibilityLiveRegion="polite">
      <Text style={{ color: c.errorText, fontSize: 14 }}>{error}</Text>
    </View>
  );
}

function GoogleButtonInner({ clientId, webClientId, onIdToken, onError, disabled }: {
  clientId: string;
  webClientId?: string;
  onIdToken: (idToken: string) => void;
  onError: () => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [request, response, promptAsync] = Google.useIdTokenAuthRequest({
    androidClientId: Platform.OS === "android" ? clientId : undefined,
    iosClientId: Platform.OS === "ios" ? clientId : undefined,
    webClientId,
    selectAccount: true,
  });

  useEffect(() => {
    if (!response) return;
    if (response.type === "success") {
      const idToken = response.params.id_token ?? response.authentication?.idToken;
      if (idToken) onIdToken(idToken);
      else onError();
    } else if (response.type === "error") {
      onError();
    }
    // "cancel" / "dismiss": the farmer closed the Google page; nothing to report.
  }, [response]);

  return (
    <Pressable
      onPress={() => void promptAsync()}
      disabled={!request || disabled}
      accessibilityRole="button"
      accessibilityState={{ disabled: !request || !!disabled }}
      style={({ pressed }) => [st.google, (!request || disabled) && { opacity: 0.6 }, pressed && { backgroundColor: "#f1f3f4" }]}
    >
      <Text style={st.googleG}>G</Text>
      <Text style={st.googleText}>{t("auth.google")}</Text>
    </Pressable>
  );
}

/** "Sign in with Google": shown when this platform has a Google client ID configured and the server has Google sign-in on. */
function GoogleBlock({ run, setError, busy }: { run: (fn: () => Promise<unknown>) => Promise<void>; setError: (e: string | null) => void; busy: boolean }) {
  const { t } = useTranslation();
  const { api, language, meta } = useMobile();
  if (!NATIVE_GOOGLE_ID || !meta?.google_client_id) return null;
  return (
    <>
      <Divider label={t("auth.orContinue")} />
      <GoogleButtonInner
        clientId={NATIVE_GOOGLE_ID}
        webClientId={meta.google_client_id}
        disabled={busy}
        onIdToken={(idToken) => void run(() => api.googleLogin(idToken, language ?? undefined))}
        onError={() => setError(t("login.googleFailed"))}
      />
    </>
  );
}

function useRunner() {
  const { t } = useTranslation();
  const { refreshAuth } = useMobile();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>, finishLogin = true) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      if (finishLogin) refreshAuth();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("ask.error"));
    } finally {
      setBusy(false);
    }
  };
  return { run, error, setError, busy };
}

function LoginForm({ onSignup }: { onSignup: () => void }) {
  const { t } = useTranslation();
  const { api, language, meta, chooseGuest } = useMobile();
  const { run, error, setError, busy } = useRunner();
  const [otpMode, setOtpMode] = useState(false);
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [devCode, setDevCode] = useState<string | null>(null);
  const lang = language ?? undefined;

  const submit = () => {
    if (!otpMode) return void run(() => api.passwordLogin(identifier.trim(), password, lang));
    if (!sent)
      return void run(async () => {
        const res = await api.requestOtp(identifier);
        setSent(true);
        setDevCode(res.dev_code ?? null);
      }, false);
    void run(() => api.verifyOtp(identifier, code, lang));
  };

  const switchMode = () => {
    setOtpMode((m) => !m);
    setSent(false);
    setCode("");
    setDevCode(null);
    setError(null);
  };

  const canSubmit = otpMode ? (sent ? code.length >= 4 : identifier.replace(/\D/g, "").length >= 10) : identifier.trim().length >= 3 && password.length > 0;

  return (
    <>
      <Header icon="₹" title={t("auth.welcome")} subtitle={t("auth.signInSub")} />
      <View style={{ gap: 16 }}>
        {otpMode ? (
          <>
            <Field
              label={t("login.phone")}
              icon="📱"
              placeholder={t("auth.mobilePh")}
              keyboardType="phone-pad"
              autoComplete="tel"
              textContentType="telephoneNumber"
              value={identifier}
              onChangeText={setIdentifier}
              editable={!sent}
            />
            {sent && (
              <View style={{ gap: 6 }}>
                <Field
                  label={t("login.code")}
                  icon="🔑"
                  keyboardType="number-pad"
                  autoComplete="sms-otp"
                  textContentType="oneTimeCode"
                  maxLength={6}
                  value={code}
                  onChangeText={(v) => setCode(v.replace(/\D/g, ""))}
                  style={{ letterSpacing: 6 }}
                />
                {devCode && <Text style={{ color: c.muted, fontSize: 13 }}>{t("login.devCode", { code: devCode })}</Text>}
              </View>
            )}
          </>
        ) : (
          <>
            <Field
              label={t("auth.email")}
              icon="✉️"
              placeholder={t("auth.emailOrMobilePh")}
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
              autoComplete="username"
              textContentType="username"
              value={identifier}
              onChangeText={setIdentifier}
            />
            <PasswordField label={t("auth.password")} placeholder={t("auth.passwordPh")} value={password} onChangeText={setPassword} />
          </>
        )}
        <ErrorText error={error} />
        <PrimaryButton label={otpMode && !sent ? t("login.sendCode") : t("auth.signIn")} trailing="→" onPress={submit} disabled={!canSubmit} busy={busy} />
        <Pressable onPress={switchMode} hitSlop={8} accessibilityRole="button">
          <Text style={st.link}>{otpMode ? t("auth.usePassword") : t("auth.useOtp")}</Text>
        </Pressable>
      </View>

      <GoogleBlock run={run} setError={setError} busy={busy} />

      <Divider label={t("auth.noAccount")} />
      <PrimaryButton label={t("auth.signUp")} leading="✨" onPress={onSignup} accent />

      {!meta?.auth_required && (
        <Pressable onPress={() => chooseGuest(true)} style={[s.btnGhost, { marginTop: 12 }]} accessibilityRole="button">
          <Text style={s.btnGhostText}>{t("login.guest")}</Text>
        </Pressable>
      )}

      <View style={st.badges}>
        <Text style={st.badge}>🛡️ {t("auth.secure")}</Text>
        <Text style={st.badge}>⚡ {t("auth.fast")}</Text>
      </View>
    </>
  );
}

function SignupForm({ onLogin }: { onLogin: () => void }) {
  const { t } = useTranslation();
  const { api, language } = useMobile();
  const { run, error, setError, busy } = useRunner();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");

  const canSubmit = name.trim().length > 0 && /\S+@\S+\.\S+/.test(email) && password.length >= 6;
  const submit = () =>
    void run(() => api.signup({ name: name.trim(), email: email.trim(), phone: phone.trim() || undefined, password, language: language ?? undefined }));

  return (
    <>
      <Header icon="₹" title={t("auth.createAccount")} subtitle={t("auth.joinSub", { app: t("app.name") })} />
      <View style={{ gap: 16 }}>
        <Field label={t("auth.fullName")} icon="👤" placeholder={t("auth.namePh")} autoComplete="name" textContentType="name" autoCapitalize="words" value={name} onChangeText={setName} />
        <Field
          label={t("auth.email")}
          icon="✉️"
          placeholder={t("auth.emailPh")}
          keyboardType="email-address"
          autoCapitalize="none"
          autoCorrect={false}
          autoComplete="email"
          textContentType="emailAddress"
          value={email}
          onChangeText={setEmail}
        />
        <Field label={t("auth.phone")} icon="📞" placeholder={t("auth.mobilePh")} keyboardType="phone-pad" autoComplete="tel" textContentType="telephoneNumber" value={phone} onChangeText={setPhone} />
        <PasswordField label={t("auth.password")} placeholder={t("auth.minChars")} value={password} onChangeText={setPassword} isNew />
        <ErrorText error={error} />
        <PrimaryButton label={t("auth.signUp")} trailing="→" onPress={submit} disabled={!canSubmit} busy={busy} />
      </View>
      <GoogleBlock run={run} setError={setError} busy={busy} />
      <View style={st.footer}>
        <Text style={{ color: c.muted, fontSize: 15, textAlign: "center" }}>
          {t("auth.haveAccount")}{" "}
          <Text onPress={onLogin} style={{ color: c.accentStrong, fontWeight: "700" }} accessibilityRole="link">
            {t("auth.signIn")}
          </Text>
        </Text>
      </View>
    </>
  );
}

export function AuthScreen() {
  const [mode, setMode] = useState<"login" | "signup">("login");
  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: c.bg }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView contentContainerStyle={st.scroll} keyboardShouldPersistTaps="handled">
        <View style={st.card}>
          <LanguageSwitch />
          {mode === "login" ? <LoginForm onSignup={() => setMode("signup")} /> : <SignupForm onLogin={() => setMode("login")} />}
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const st = StyleSheet.create({
  scroll: { flexGrow: 1, justifyContent: "center", padding: 16 },
  card: { backgroundColor: c.card, borderColor: c.cardEdge, borderWidth: 1, borderRadius: 20, padding: 22 },
  logo: { width: 60, height: 60, borderRadius: 16, backgroundColor: c.primary, alignItems: "center", justifyContent: "center", marginBottom: 14 },
  title: { color: c.text, fontSize: 26, fontWeight: "700", letterSpacing: -0.3 },
  subtitle: { color: c.muted, fontSize: 16, marginTop: 6 },
  label: { color: c.text, fontSize: 15, fontWeight: "600" },
  field: { flexDirection: "row", alignItems: "center", minHeight: 50, borderRadius: 14, borderWidth: 1, borderColor: c.fieldEdge, backgroundColor: c.field, paddingLeft: 12 },
  fieldIcon: { fontSize: 16, width: 26, color: c.muted },
  input: { flex: 1, color: c.text, fontSize: 16, paddingVertical: 12, paddingRight: 12 },
  eye: { paddingHorizontal: 12, height: 48, justifyContent: "center" },
  primary: { minHeight: 50, borderRadius: 12, backgroundColor: c.primary, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingHorizontal: 16 },
  accentBtn: { backgroundColor: c.amber },
  primaryText: { color: c.primaryText, fontSize: 17, fontWeight: "700" },
  link: { color: c.accent, fontSize: 14, fontWeight: "500", textAlign: "center" },
  divider: { flexDirection: "row", alignItems: "center", gap: 10, marginVertical: 20 },
  rule: { flex: 1, height: 1, backgroundColor: c.cardEdge },
  badges: { flexDirection: "row", justifyContent: "center", gap: 20, marginTop: 18 },
  badge: { color: c.accent, fontSize: 14 },
  error: { borderRadius: 10, borderWidth: 1, borderColor: c.errorEdge, backgroundColor: c.errorBg, paddingHorizontal: 12, paddingVertical: 8 },
  google: {
    minHeight: 50,
    borderRadius: 14,
    backgroundColor: "#ffffff",
    borderWidth: 1,
    borderColor: "#dadce0",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    paddingHorizontal: 16,
  },
  googleG: { fontSize: 20, fontWeight: "800", color: "#4285F4" },
  googleText: { fontSize: 16, fontWeight: "600", color: "#3c4043" },
  langRow: { flexDirection: "row", alignSelf: "center", backgroundColor: c.bg, borderColor: c.cardEdge, borderWidth: 1, borderRadius: 12, padding: 4, marginBottom: 18 },
  langBtn: { minHeight: 36, paddingHorizontal: 14, borderRadius: 9, alignItems: "center", justifyContent: "center" },
  langBtnOn: { backgroundColor: c.card, borderWidth: 1, borderColor: c.cardEdge },
  langText: { fontSize: 15, fontWeight: "600", color: c.muted },
  footer: { marginTop: 20, paddingTop: 18, borderTopWidth: 1, borderTopColor: c.cardEdge },
});
