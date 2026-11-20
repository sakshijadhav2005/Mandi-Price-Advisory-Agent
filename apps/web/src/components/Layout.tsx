import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";
import { useApp } from "../lib/app-context";
import { useOnline } from "../lib/online";
import { ChartIcon, ChatIcon, ClockIcon, GearIcon } from "./Icons";

const tabs = [
  { to: "/", key: "nav.ask", Icon: ChatIcon, end: true },
  { to: "/prices", key: "nav.prices", Icon: ChartIcon, end: false },
  { to: "/history", key: "nav.history", Icon: ClockIcon, end: false },
  { to: "/settings", key: "nav.settings", Icon: GearIcon, end: false },
];

const LOCALE: Record<string, string> = { en: "en-IN", hi: "hi-IN", mr: "mr-IN" };

/** The rupee tile used as the app mark: amber on the dark rate board. */
export function BrandMark({ size = "md" }: { size?: "md" | "lg" }) {
  const box = size === "lg" ? "h-16 w-16 rounded-2xl text-4xl" : "h-10 w-10 rounded-lg text-xl";
  return (
    <div className={`grid shrink-0 place-items-center bg-board font-mono font-semibold text-board-ink shadow-[inset_0_0_0_1px_rgb(255_255_255/0.08)] ${box}`} aria-hidden>
      ₹
    </div>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { language } = useApp();
  const online = useOnline();
  const today = new Intl.DateTimeFormat(`${LOCALE[language ?? "en"] ?? "en-IN"}-u-nu-latn`, { day: "2-digit", month: "short" }).format(new Date());
  return (
    <div className="mx-auto flex min-h-[100dvh] max-w-2xl flex-col">
      <header className="sticky top-0 z-10 border-b border-line bg-paper/90 px-4 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))] backdrop-blur-md">
        <div className="flex items-center gap-3">
          <BrandMark />
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-xl font-bold leading-tight tracking-tight">{t("app.name")}</h1>
            <p className="truncate text-xs text-muted">{t("app.tagline")}</p>
          </div>
          <p className="num flex shrink-0 items-center gap-1.5 text-xs font-semibold uppercase text-muted">
            <span className={`h-2 w-2 rounded-full ${online ? "bg-leaf" : "bg-turmeric"}`} aria-hidden />
            {today}
          </p>
        </div>
      </header>
      {!online && (
        <p role="status" className="border-b border-turmeric/40 bg-turmeric-soft px-4 py-2 text-sm font-medium text-turmeric-ink">
          {t("offline.banner")}
        </p>
      )}
      <main className="flex-1 px-4 pb-32 pt-5">{children}</main>
      <nav
        className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface/95 backdrop-blur-md"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
        aria-label="Main"
      >
        <ul className="mx-auto grid max-w-2xl grid-cols-4">
          {tabs.map(({ to, key, Icon, end }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={end}
                className={({ isActive }) =>
                  `relative flex min-h-[64px] flex-col items-center justify-center gap-1 text-xs font-semibold transition-colors ${
                    isActive ? "text-leaf-ink" : "text-muted hover:text-ink"
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <span
                      className={`absolute inset-x-4 top-0 h-[3px] rounded-b-full transition-colors ${isActive ? "bg-leaf" : "bg-transparent"}`}
                      aria-hidden
                    />
                    <Icon />
                    {t(key)}
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
