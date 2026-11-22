import { LANGUAGES, type LanguageCode } from "@mandi/i18n";
import { ApiError } from "@mandi/shared";
import { useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { GoogleSignInButton } from "../components/GoogleSignInButton";
import { NativeGoogleButton } from "../components/NativeGoogleButton";
import {
  ArrowRightIcon,
  BoltIcon,
  EyeIcon,
  EyeOffIcon,
  LockIcon,
  MailIcon,
  PhoneIcon,
  ShieldIcon,
  SparkleIcon,
  TractorIcon,
  UserIcon,
} from "../components/Icons";
import { useApp } from "../lib/app-context";

/*
 * Sign in / sign up, built from the app theme only (paper, surface, ink, leaf,
 * turmeric), so it follows light and dark mode like every other page.
 */

const primaryBtn = "btn-primary w-full";
/** Second call to action ("Sign up" on the login card): the turmeric accent from the rate board. */
const accentBtn = "btn w-full bg-turmeric text-board shadow-[inset_0_-2px_0_rgb(0_0_0/0.18)] hover:bg-turmeric/90";

function AuthCard({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-md pt-2">
      <div className="card rounded-2xl p-6 sm:p-8">
        <LanguageSwitch />
        {children}
      </div>
    </div>
  );
}

/** English / हिंदी / मराठी, the same setting as in Settings (saved, switches the whole app). */
function LanguageSwitch() {
  const { language, setLanguage } = useApp();
  return (
    <div role="radiogroup" aria-label="Language / भाषा" className="mb-5 flex justify-center">
      <div className="inline-flex rounded-lg border border-line bg-sunken p-1">
        {LANGUAGES.map((l) => {
          const on = language === l.code;
          return (
            <button
              key={l.code}
              type="button"
              role="radio"
              aria-checked={on}
              lang={l.code}
              onClick={() => setLanguage(l.code as LanguageCode)}
              className={`min-h-[36px] rounded-md px-3 text-sm font-semibold transition-colors ${on ? "bg-surface text-leaf-ink shadow-[0_1px_0_rgb(var(--line))]" : "text-muted hover:text-ink"}`}
            >
              {l.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function CardHeader({ icon, title, subtitle }: { icon: ReactNode; title: string; subtitle: string }) {
  return (
    <div className="mb-6 text-center">
      <div className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-board text-board-ink shadow-[inset_0_0_0_1px_rgb(255_255_255/0.08)]">
        {icon}
      </div>
      <h2 className="font-display text-3xl font-bold tracking-tight text-ink">{title}</h2>
      <p className="mt-2 text-muted">{subtitle}</p>
    </div>
  );
}

function Field({
  id,
  label,
  icon,
  trailing,
  className = "",
  ...input
}: { id: string; label: string; icon: ReactNode; trailing?: ReactNode } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-semibold text-ink">
        {label}
      </label>
      <div className="relative">
        <span className="pointer-events-none absolute inset-y-0 left-3.5 flex items-center text-muted">{icon}</span>
        <input
          id={id}
          {...input}
          className={`input pl-11 ${trailing ? "pr-11" : ""} disabled:bg-sunken disabled:opacity-70 ${className}`}
        />
        {trailing && <span className="absolute inset-y-0 right-2 flex items-center">{trailing}</span>}
      </div>
    </div>
  );
}

function PasswordField({ id, label, placeholder, value, onChange, autoComplete }: {
  id: string;
  label: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete: string;
}) {
  const { t } = useTranslation();
  const [show, setShow] = useState(false);
  return (
    <Field
      id={id}
      label={label}
      icon={<LockIcon />}
      type={show ? "text" : "password"}
      placeholder={placeholder}
      autoComplete={autoComplete}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      trailing={
        <button
          type="button"
          onClick={() => setShow((s) => !s)}
          className="grid h-9 w-9 place-items-center rounded-lg text-muted hover:bg-sunken hover:text-ink"
          aria-label={show ? t("auth.hidePassword") : t("auth.showPassword")}
          aria-pressed={show}
        >
          {show ? <EyeOffIcon /> : <EyeIcon />}
        </button>
      }
    />
  );
}

function Divider({ children }: { children: ReactNode }) {
  return (
    <div className="my-5 flex items-center gap-3 text-sm text-muted">
      <span className="h-px flex-1 bg-line" aria-hidden />
      {children}
      <span className="h-px flex-1 bg-line" aria-hidden />
    </div>
  );
}

function ErrorText({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-lg border border-chilli/30 bg-chilli-soft px-3 py-2 text-sm text-chilli-ink">
      {error}
    </p>
  );
}

function useAuthRunner() {
  const { t } = useTranslation();
  const { refreshAuth } = useApp();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>, done = true) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      if (done) {
        refreshAuth();
        navigate("/", { replace: true });
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("ask.error"));
    } finally {
      setBusy(false);
    }
  };
  return { run, error, setError, busy };
}

function GoogleBlock({ run, onError }: { run: (fn: () => Promise<unknown>) => Promise<void>; onError: (msg: string) => void }) {
  const { t } = useTranslation();
  const { api, language, meta } = useApp();
  // Inside the Android/iOS app (Capacitor) Google's web sign-in opens in the outside browser,
  // which cannot hand the result back ("origin_mismatch"), so the app uses native sign-in.
  const inNativeApp = !!(window as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor?.isNativePlatform?.();
  if (!meta?.google_client_id) return null;
  return (
    <>
      <Divider>{t("auth.orContinue")}</Divider>
      <div className="overflow-hidden rounded-lg">
        {inNativeApp ? (
          <NativeGoogleButton
            clientId={meta.google_client_id}
            onCredential={(credential) => void run(() => api.googleLogin(credential, language ?? undefined))}
            onError={() => onError(t("login.googleFailed"))}
          />
        ) : (
          <GoogleSignInButton
            clientId={meta.google_client_id}
            locale={language ?? "en"}
            onCredential={(credential) => void run(() => api.googleLogin(credential, language ?? undefined))}
            onError={() => onError(t("login.googleFailed"))}
          />
        )}
      </div>
    </>
  );
}

export function LoginPage() {
  const { t } = useTranslation();
  const { api, language, meta } = useApp();
  const navigate = useNavigate();
  const { run, error, setError, busy } = useAuthRunner();
  const [otpMode, setOtpMode] = useState(false);
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");

  // Mobile one-time-code sign-in (kept for farmers without an email address)
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [devCode, setDevCode] = useState<string | null>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!otpMode) return void run(() => api.passwordLogin(identifier, password, language ?? undefined));
    if (!sent)
      return void run(async () => {
        const res = await api.requestOtp(identifier);
        setSent(true);
        setDevCode(res.dev_code ?? null);
      }, false);
    void run(() => api.verifyOtp(identifier, code, language ?? undefined));
  };

  const switchMode = () => {
    setOtpMode((m) => !m);
    setSent(false);
    setCode("");
    setDevCode(null);
    setError(null);
  };

  const canSubmit = otpMode
    ? sent
      ? code.length >= 4
      : identifier.replace(/\D/g, "").length >= 10
    : identifier.trim().length >= 3 && password.length > 0;

  return (
    <AuthCard>
      <CardHeader icon={<TractorIcon className="h-7 w-7" />} title={t("auth.welcome")} subtitle={t("auth.signInSub")} />
      <form onSubmit={submit} className="space-y-4" noValidate>
        {otpMode ? (
          <>
            <Field
              id="identifier"
              label={t("login.phone")}
              icon={<PhoneIcon />}
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              placeholder={t("auth.mobilePh")}
              value={identifier}
              disabled={sent}
              onChange={(e) => setIdentifier(e.target.value)}
            />
            {sent && (
              <div>
                <Field
                  id="code"
                  label={t("login.code")}
                  icon={<LockIcon />}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  className="tracking-[0.4em]"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                />
                {devCode && <p className="mt-1.5 text-sm text-muted">{t("login.devCode", { code: devCode })}</p>}
              </div>
            )}
          </>
        ) : (
          <>
            <Field
              id="identifier"
              label={t("auth.email")}
              icon={<MailIcon />}
              type="text"
              inputMode="email"
              autoComplete="username"
              placeholder={t("auth.emailOrMobilePh")}
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
            />
            <PasswordField
              id="password"
              label={t("auth.password")}
              placeholder={t("auth.passwordPh")}
              autoComplete="current-password"
              value={password}
              onChange={setPassword}
            />
          </>
        )}
        <ErrorText error={error} />
        <button type="submit" className={primaryBtn} disabled={busy || !canSubmit}>
          {otpMode && !sent ? t("login.sendCode") : t("auth.signIn")}
          <ArrowRightIcon className="h-4 w-4" />
        </button>
        <button type="button" onClick={switchMode} className="w-full text-center text-sm font-medium text-leaf-ink underline-offset-4 hover:underline">
          {otpMode ? t("auth.usePassword") : t("auth.useOtp")}
        </button>
      </form>

      <GoogleBlock run={run} onError={setError} />

      <Divider>{t("auth.noAccount")}</Divider>
      <button type="button" className={accentBtn} onClick={() => navigate("/signup")}>
        <SparkleIcon className="h-5 w-5" />
        {t("auth.signUp")}
      </button>

      {!meta?.auth_required && (
        <button type="button" className="btn-ghost mt-3 w-full" onClick={() => navigate("/")}>
          {t("login.guest")}
        </button>
      )}

      <div className="mt-5 flex items-center justify-center gap-5 text-sm text-leaf-ink">
        <span className="flex items-center gap-1.5">
          <ShieldIcon className="h-4 w-4" />
          {t("auth.secure")}
        </span>
        <span className="flex items-center gap-1.5">
          <BoltIcon className="h-4 w-4" />
          {t("auth.fast")}
        </span>
      </div>
    </AuthCard>
  );
}

export function SignupPage() {
  const { t } = useTranslation();
  const { api, language } = useApp();
  const { run, error, setError, busy } = useAuthRunner();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(() =>
      api.signup({ name: name.trim(), email: email.trim(), phone: phone.trim() || undefined, password, language: language ?? undefined }),
    );
  };

  const canSubmit = name.trim().length > 0 && /\S+@\S+\.\S+/.test(email) && password.length >= 6;

  return (
    <AuthCard>
      <CardHeader icon={<UserIcon className="h-7 w-7" />} title={t("auth.createAccount")} subtitle={t("auth.joinSub", { app: t("app.name") })} />
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="name" label={t("auth.fullName")} icon={<UserIcon />} autoComplete="name" placeholder={t("auth.namePh")} value={name} onChange={(e) => setName(e.target.value)} />
          <Field id="email" label={t("auth.email")} icon={<MailIcon />} type="email" autoComplete="email" placeholder={t("auth.emailPh")} value={email} onChange={(e) => setEmail(e.target.value)} />
          <Field id="phone" label={t("auth.phone")} icon={<PhoneIcon />} type="tel" inputMode="tel" autoComplete="tel" placeholder={t("auth.mobilePh")} value={phone} onChange={(e) => setPhone(e.target.value)} />
          <PasswordField id="password" label={t("auth.password")} placeholder={t("auth.minChars")} autoComplete="new-password" value={password} onChange={setPassword} />
        </div>
        <ErrorText error={error} />
        <button type="submit" className={primaryBtn} disabled={busy || !canSubmit}>
          {t("auth.signUp")}
          <ArrowRightIcon className="h-4 w-4" />
        </button>
      </form>

      <GoogleBlock run={run} onError={setError} />

      <div className="mt-5 border-t border-line pt-5 text-center text-sm text-muted">
        {t("auth.haveAccount")}{" "}
        <Link to="/login" className="font-semibold text-leaf-ink hover:underline">
          {t("auth.signIn")}
        </Link>
      </div>
    </AuthCard>
  );
}
