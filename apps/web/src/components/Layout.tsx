import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";
import { useOnline } from "../lib/online";
import { ChartIcon, ChatIcon, ClockIcon, GearIcon } from "./Icons";

const tabs = [
  { to: "/", key: "nav.ask", Icon: ChatIcon, end: true },
  { to: "/prices", key: "nav.prices", Icon: ChartIcon, end: false },
  { to: "/history", key: "nav.history", Icon: ClockIcon, end: false },
  { to: "/settings", key: "nav.settings", Icon: GearIcon, end: false },
];

export function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const online = useOnline();
  return (
    <div className="mx-auto flex min-h-[100dvh] max-w-2xl flex-col">
      <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-stone-200 bg-soil-50/95 px-4 py-3 backdrop-blur dark:border-stone-800 dark:bg-stone-950/95">
        <div className="grid h-9 w-9 place-items-center rounded-xl bg-leaf-600 text-lg font-bold text-white" aria-hidden>
          ₹
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-lg font-bold leading-tight">{t("app.name")}</h1>
          <p className="truncate text-xs text-stone-500 dark:text-stone-400">{t("app.tagline")}</p>
        </div>
      </header>
      {!online && (
        <p role="status" className="bg-amber-200 px-4 py-2 text-sm font-medium text-amber-950">
          {t("offline.banner")}
        </p>
      )}
      <main className="flex-1 px-4 pb-28 pt-4">{children}</main>
      <nav
        className="fixed inset-x-0 bottom-0 z-20 border-t border-stone-200 bg-white/95 backdrop-blur dark:border-stone-800 dark:bg-stone-900/95"
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
                  `flex min-h-[60px] flex-col items-center justify-center gap-0.5 text-xs font-medium ${
                    isActive ? "text-leaf-600 dark:text-leaf-500" : "text-stone-500 dark:text-stone-400"
                  }`
                }
              >
                <Icon />
                {t(key)}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
