import { LANGUAGES } from "@mandi/i18n";
import { displayName } from "@mandi/shared";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useApp } from "../lib/app-context";

export function SettingsPage() {
  const { t } = useTranslation();
  const { language, setLanguage, autoSpeak, setAutoSpeak, keepRecordings, setKeepRecordings, apiBase, setApiBase, loggedIn, logout, metaError, meta, district, setDistrict } = useApp();
  const [server, setServer] = useState(apiBase);

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold tracking-tight">{t("settings.title")}</h2>
      <section className="card space-y-3">
        <h3 className="eyebrow">{t("settings.language")}</h3>
        <div className="grid grid-cols-3 gap-2">
          {LANGUAGES.map((l) => (
            <button key={l.code} type="button" lang={l.code} className={language === l.code ? "btn-primary" : "btn-ghost"} onClick={() => setLanguage(l.code)}>
              {l.label}
            </button>
          ))}
        </div>
        <label className="flex min-h-[48px] items-center gap-3">
          <input type="checkbox" className="h-6 w-6 accent-[rgb(var(--leaf))]" checked={autoSpeak} onChange={(e) => setAutoSpeak(e.target.checked)} />
          {t("settings.speakAnswers")}
        </label>
        {meta?.voice.server_stt && meta.voice.stores_recordings && (
          <label className="flex min-h-[48px] items-start gap-3">
            <input type="checkbox" className="mt-1 h-6 w-6 shrink-0 accent-[rgb(var(--leaf))]" checked={keepRecordings} onChange={(e) => setKeepRecordings(e.target.checked)} />
            <span>
              {t("settings.keepRecordings")}
              <span className="block text-sm text-muted">{t("settings.keepRecordingsHelp")}</span>
            </span>
          </label>
        )}
      </section>

      {meta?.districts && meta.districts.length > 1 && (
        <section className="card space-y-3">
          <h3 className="eyebrow">{t("settings.district")}</h3>
          <div className="grid grid-cols-2 gap-2">
            {meta.districts.map((d) => (
              <button
                key={d.id}
                type="button"
                className={(district ?? meta.districts![0].id) === d.id ? "btn-primary" : "btn-ghost"}
                onClick={() => setDistrict(d.id)}
              >
                {displayName(d, language ?? "en")}
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="card space-y-3">
        <h3 className="eyebrow">{t("settings.account")}</h3>
        {loggedIn ? (
          <button type="button" className="btn-ghost" onClick={logout}>
            {t("login.logout")}
          </button>
        ) : (
          <>
            <p className="text-sm text-muted">{t("settings.guest")}</p>
            <Link to="/login" className="btn-primary">
              {t("login.verify")}
            </Link>
          </>
        )}
      </section>

      <section className="card space-y-2">
        <label className="label" htmlFor="server">
          {t("settings.server")}
        </label>
        <div className="flex gap-2">
          <input id="server" className="input" value={server} onChange={(e) => setServer(e.target.value)} inputMode="url" />
          <button type="button" className="btn-ghost" onClick={() => setApiBase(server.trim())}>
            OK
          </button>
        </div>
        {metaError && <p className="text-sm text-chilli-ink">{metaError}</p>}
      </section>

      <Link to="/admin" className="block text-center text-sm text-muted underline">
        Admin
      </Link>
    </div>
  );
}
