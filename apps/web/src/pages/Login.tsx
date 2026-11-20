import { ApiError } from "@mandi/shared";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { GoogleSignInButton } from "../components/GoogleSignInButton";
import { useApp } from "../lib/app-context";

export function LoginPage() {
  const { t } = useTranslation();
  const { api, language, refreshAuth, meta } = useApp();
  const navigate = useNavigate();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [devCode, setDevCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("ask.error"));
    } finally {
      setBusy(false);
    }
  };

  const requestCode = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const res = await api.requestOtp(phone);
      setSent(true);
      setDevCode(res.dev_code ?? null);
    });
  };

  const verify = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.verifyOtp(phone, code, language ?? undefined);
      refreshAuth();
      navigate("/", { replace: true });
    });
  };

  const googleLogin = (credential: string) =>
    void run(async () => {
      await api.googleLogin(credential, language ?? undefined);
      refreshAuth();
      navigate("/", { replace: true });
    });

  return (
    <div className="mx-auto max-w-sm space-y-4 pt-4">
      <h2 className="text-2xl font-bold tracking-tight">{t("login.title")}</h2>
      <form onSubmit={sent ? verify : requestCode} className="card space-y-3">
        <div>
          <label className="label" htmlFor="phone">
            {t("login.phone")}
          </label>
          <input id="phone" className="input num" type="tel" inputMode="tel" autoComplete="tel" value={phone} onChange={(e) => setPhone(e.target.value)} disabled={sent} />
        </div>
        {sent && (
          <div>
            <label className="label" htmlFor="code">
              {t("login.code")}
            </label>
            <input id="code" className="input num tracking-[0.4em]" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
            {devCode && <p className="mt-1 text-sm text-muted">{t("login.devCode", { code: devCode })}</p>}
          </div>
        )}
        {error && <p className="text-sm text-chilli-ink">{error}</p>}
        <button type="submit" className="btn-primary w-full" disabled={busy || (sent ? code.length < 4 : phone.replace(/\D/g, "").length < 10)}>
          {sent ? t("login.verify") : t("login.sendCode")}
        </button>
      </form>
      {meta?.google_client_id && (
        <>
          <div className="flex items-center gap-3 text-sm text-muted" aria-hidden="true">
            <span className="h-px flex-1 bg-line" />
            {t("login.or")}
            <span className="h-px flex-1 bg-line" />
          </div>
          <GoogleSignInButton
            clientId={meta.google_client_id}
            locale={language ?? "en"}
            onCredential={googleLogin}
            onError={() => setError(t("login.googleFailed"))}
          />
        </>
      )}
      {!meta?.auth_required && (
        <button type="button" className="btn-ghost w-full" onClick={() => navigate("/")}>
          {t("login.guest")}
        </button>
      )}
    </div>
  );
}
