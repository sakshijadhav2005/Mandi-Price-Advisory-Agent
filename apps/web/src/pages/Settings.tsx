import { LANGUAGES } from "@mandi/i18n";
import { displayName, type DistrictInfo } from "@mandi/shared";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { version } from "../../package.json";
import {
  ChevronDownIcon,
  ChevronRightIcon,
  GlobeIcon,
  InfoIcon,
  LogOutIcon,
  MicIcon,
  MoonIcon,
  PhoneIcon,
  PinIcon,
  ServerIcon,
  SlidersIcon,
  SpeakerIcon,
  SunIcon,
  UserIcon,
} from "../components/Icons";
import { useApp, type Theme } from "../lib/app-context";

type Me = { phone?: string | null; email?: string | null; name?: string | null };

/** Section heading: small leaf icon and title, like the groups in a phone's settings. */
function Section({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-2 px-1 text-lg font-semibold tracking-tight">
        <span className="text-leaf-ink">{icon}</span>
        {title}
      </h3>
      <div className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface shadow-[0_1px_0_rgb(var(--line))]">
        {children}
      </div>
    </section>
  );
}

/** Icon tile on the left of each row. */
function Tile({ children }: { children: ReactNode }) {
  return <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-leaf-soft text-leaf-ink">{children}</span>;
}

/** One settings row: icon tile, title and help text, and a control on the right. */
function Row({ icon, title, help, control, labelFor }: { icon: ReactNode; title: string; help?: string; control?: ReactNode; labelFor?: string }) {
  const Label = labelFor ? "label" : "div";
  return (
    <div className="flex min-h-[72px] items-center gap-3 px-4 py-3">
      <Tile>{icon}</Tile>
      <Label {...(labelFor ? { htmlFor: labelFor } : {})} className="min-w-0 flex-1">
        <span className="block font-semibold leading-snug">{title}</span>
        {help && <span className="block text-sm leading-snug text-muted">{help}</span>}
      </Label>
      {control}
    </div>
  );
}

/** On/off switch (a real button with role="switch", so screen readers announce it). */
function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative h-8 w-14 shrink-0 rounded-full transition-colors duration-200 ${checked ? "bg-leaf" : "bg-line"}`}
    >
      <span
        className={`absolute left-1 top-1 h-6 w-6 rounded-full bg-white shadow-[0_1px_3px_rgb(0_0_0/0.3)] transition-transform duration-200 ${
          checked ? "translate-x-6" : "translate-x-0"
        }`}
      />
    </button>
  );
}

/** A native select styled as a rounded pill (keeps the phone's own picker). */
function PillSelect({ id, value, onChange, children }: { id: string; value: string; onChange: (v: string) => void; children: ReactNode }) {
  return (
    <span className="relative shrink-0">
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="min-h-[44px] max-w-[9.5rem] appearance-none truncate rounded-full border border-line bg-paper py-2 pl-4 pr-9 font-semibold text-ink transition-colors hover:border-ink/30"
      >
        {children}
      </select>
      <ChevronDownIcon className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
    </span>
  );
}

/**
 * State, then district: one list of every district in India would be ~790 long.
 * Picking a state shows its districts; the first one is chosen until the farmer picks.
 */
function DistrictPicker({
  districts,
  states,
  value,
  onChange,
  lang,
  ids,
}: {
  districts: DistrictInfo[];
  states?: string[];
  value: string;
  onChange: (id: string) => void;
  lang: string;
  ids: { state: string; district: string };
}) {
  const { t } = useTranslation();
  const current = districts.find((d) => d.id === value) ?? districts[0]!;
  const [state, setState] = useState(current.state);
  useEffect(() => setState(current.state), [current.state]);
  const allStates = useMemo(() => states ?? [...new Set(districts.map((d) => d.state))].sort(), [states, districts]);
  const inState = useMemo(
    () => districts.filter((d) => d.state === state).sort((a, b) => displayName(a, lang).localeCompare(displayName(b, lang))),
    [districts, state, lang],
  );
  const pickState = (s: string) => {
    setState(s);
    const first = districts.filter((d) => d.state === s).sort((a, b) => a.name.localeCompare(b.name))[0];
    if (first && current.state !== s) onChange(first.id);
  };
  // Full-width selects: state names run long ("Dadra and Nagar Haveli and Daman and Diu").
  const select = "input appearance-none truncate rounded-full bg-paper pr-10 font-semibold";
  const known = inState.some((d) => d.id === value);
  return (
    <div className="space-y-3 px-4 py-3">
      <div className="flex items-center gap-3">
        <Tile>
          <PinIcon className="h-5 w-5" />
        </Tile>
        <div className="min-w-0 flex-1">
          <span className="block font-semibold leading-snug">{t("settings.district")}</span>
          <span className="block text-sm leading-snug text-muted">{t("settings.districtHelp")}</span>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor={ids.state}>
            {t("settings.state")}
          </label>
          <span className="relative block">
            <select id={ids.state} className={select} value={state} onChange={(e) => pickState(e.target.value)}>
              {allStates.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <ChevronDownIcon className="pointer-events-none absolute right-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          </span>
        </div>
        <div>
          <label className="label" htmlFor={ids.district}>
            {t("settings.district")}
          </label>
          <span className="relative block">
            <select id={ids.district} className={select} value={known ? value : ""} onChange={(e) => onChange(e.target.value)}>
              {!known && <option value="" disabled />}
              {inState.map((d) => (
                <option key={d.id} value={d.id}>
                  {displayName(d, lang)}
                </option>
              ))}
            </select>
            <ChevronDownIcon className="pointer-events-none absolute right-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          </span>
        </div>
      </div>
    </div>
  );
}

const THEMES:{ value: Theme; Icon: (p: { className?: string }) => JSX.Element; key: string }[] = [
  { value: "light", Icon: SunIcon, key: "settings.themeLight" },
  { value: "dark", Icon: MoonIcon, key: "settings.themeDark" },
  { value: "system", Icon: PhoneIcon, key: "settings.themeSystem" },
];

function initials(me: Me | null): string {
  const source = me?.name || me?.email || "";
  const letters = source
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
  return letters || "";
}

export function SettingsPage() {
  const { t } = useTranslation();
  const app = useApp();
  const { api, language, setLanguage, autoSpeak, setAutoSpeak, keepRecordings, setKeepRecordings, apiBase, setApiBase, loggedIn, logout, metaError, meta, district, setDistrict, theme, setTheme } = app;
  const [server, setServer] = useState(apiBase);
  const [me, setMe] = useState<Me | null>(null);
  const ids = { lang: useId(), state: useId(), district: useId(), server: useId() };

  useEffect(() => {
    if (!loggedIn) {
      setMe(null);
      return;
    }
    let live = true;
    api
      .me()
      .then((m) => live && setMe(m))
      .catch(() => live && setMe(null));
    return () => {
      live = false;
    };
  }, [api, loggedIn]);

  const lang = language ?? "en";
  const name = loggedIn ? me?.name || me?.phone || me?.email || t("settings.signedIn") : t("settings.guestName");
  const detail = loggedIn ? [me?.email, me?.name ? me?.phone : null].filter(Boolean).join(" · ") || null : t("settings.guestHint");
  const connected = !!meta && !metaError;

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h2 className="text-3xl font-bold tracking-tight">{t("settings.title")}</h2>
        <p className="text-muted">{t("settings.subtitle")}</p>
      </div>

      {/* Profile card */}
      <section className="flex items-center gap-4 rounded-2xl border border-line bg-surface p-4 shadow-[0_1px_0_rgb(var(--line))]">
        <span
          className={`grid h-16 w-16 shrink-0 place-items-center rounded-full font-display text-2xl font-bold ${
            loggedIn ? "bg-leaf text-white" : "bg-sunken text-muted"
          }`}
          aria-hidden
        >
          {(loggedIn && initials(me)) || <UserIcon className="h-8 w-8" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="num truncate text-lg font-semibold leading-tight [font-family:inherit]">{name}</p>
          {detail && <p className="text-sm leading-snug text-muted">{detail}</p>}
        </div>
        {loggedIn ? (
          <button type="button" onClick={logout} className="btn-ghost min-h-[44px] shrink-0 px-3 text-sm" aria-label={t("login.logout")}>
            <LogOutIcon className="h-5 w-5" />
            <span className="hidden sm:inline">{t("login.logout")}</span>
          </button>
        ) : (
          <Link to="/login" className="btn-primary min-h-[44px] shrink-0 px-3 text-sm">
            {t("settings.signIn")}
            <ChevronRightIcon className="h-4 w-4" />
          </Link>
        )}
      </section>

      <Section icon={<SlidersIcon />} title={t("settings.preferences")}>
        <Row
          icon={<GlobeIcon />}
          title={t("settings.language")}
          help={t("settings.languageHelp")}
          labelFor={ids.lang}
          control={
            <PillSelect id={ids.lang} value={lang} onChange={(v) => setLanguage(v as typeof lang)}>
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code} lang={l.code}>
                  {l.label}
                </option>
              ))}
            </PillSelect>
          }
        />
        <div className="space-y-3 px-4 py-3">
          <div className="flex items-center gap-3">
            <Tile>{theme === "dark" ? <MoonIcon /> : <SunIcon />}</Tile>
            <div className="min-w-0 flex-1">
              <span className="block font-semibold leading-snug">{t("settings.appearance")}</span>
              <span className="block text-sm leading-snug text-muted">{t("settings.appearanceHelp")}</span>
            </div>
          </div>
          <div role="radiogroup" aria-label={t("settings.appearance")} className="grid grid-cols-3 gap-1 rounded-xl bg-sunken p-1">
            {THEMES.map(({ value, Icon, key }) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={theme === value}
                onClick={() => setTheme(value)}
                className={`flex min-h-[44px] items-center justify-center gap-1.5 rounded-lg px-2 text-sm font-semibold transition-colors ${
                  theme === value ? "bg-surface text-ink shadow-[0_1px_2px_rgb(var(--ink)/0.15)]" : "text-muted hover:text-ink"
                }`}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{t(key)}</span>
              </button>
            ))}
          </div>
        </div>
        {meta?.districts && meta.districts.length > 1 && (
          <DistrictPicker
            districts={meta.districts}
            states={meta.states}
            value={district ?? meta.districts[0]!.id}
            onChange={setDistrict}
            lang={lang}
            ids={{ state: ids.state, district: ids.district }}
          />
        )}
      </Section>

      <Section icon={<SpeakerIcon />} title={t("settings.voice")}>
        <Row
          icon={<SpeakerIcon />}
          title={t("settings.speakAnswersTitle")}
          help={t("settings.speakAnswersHelp")}
          control={<Switch checked={autoSpeak} onChange={setAutoSpeak} label={t("settings.speakAnswersTitle")} />}
        />
        {meta?.voice.server_stt && meta.voice.stores_recordings && (
          <Row
            icon={<MicIcon className="h-5 w-5" />}
            title={t("settings.keepRecordingsTitle")}
            help={t("settings.keepRecordingsHelp")}
            control={<Switch checked={keepRecordings} onChange={setKeepRecordings} label={t("settings.keepRecordings")} />}
          />
        )}
      </Section>

      <Section icon={<ServerIcon />} title={t("settings.advanced")}>
        <details className="group">
          <summary className="flex min-h-[72px] cursor-pointer list-none items-center gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
            <Tile>
              <ServerIcon />
            </Tile>
            <span className="min-w-0 flex-1">
              <span className="block font-semibold leading-snug">{t("settings.server")}</span>
              <span className="block truncate text-sm leading-snug text-muted">{apiBase}</span>
            </span>
            <ChevronRightIcon className="h-5 w-5 shrink-0 text-muted transition-transform group-open:rotate-90" />
          </summary>
          <div className="space-y-2 px-4 pb-4">
            <label className="label" htmlFor={ids.server}>
              {t("settings.serverHelp")}
            </label>
            <div className="flex gap-2">
              <input id={ids.server} className="input" value={server} onChange={(e) => setServer(e.target.value)} inputMode="url" />
              <button type="button" className="btn-ghost shrink-0" onClick={() => setApiBase(server.trim())}>
                {t("settings.save")}
              </button>
            </div>
            {metaError && <p className="text-sm text-chilli-ink">{metaError}</p>}
          </div>
        </details>
      </Section>

      <Section icon={<InfoIcon />} title={t("settings.about")}>
        <Row
          icon={<InfoIcon />}
          title={t("settings.version")}
          help={`v${version}`}
          control={
            <span
              className={`chip shrink-0 gap-1.5 rounded-full px-3 py-1.5 text-sm ${
                connected ? "bg-leaf-soft text-leaf-ink" : "bg-chilli-soft text-chilli-ink"
              }`}
            >
              <span className={`h-2 w-2 rounded-full ${connected ? "bg-leaf" : "bg-chilli"}`} aria-hidden />
              {t(connected ? "settings.connected" : "settings.notConnected")}
            </span>
          }
        />
      </Section>
    </div>
  );
}
