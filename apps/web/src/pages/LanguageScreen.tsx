import { LANGUAGES, type LanguageCode } from "@mandi/i18n";
import { resources } from "@mandi/i18n";
import { BrandMark } from "../components/Layout";
import { useApp } from "../lib/app-context";

/** First-launch language picker. Shown in every language at once, since none is chosen yet. */
export function LanguageScreen() {
  const { setLanguage } = useApp();
  return (
    <div className="mx-auto flex min-h-[100dvh] max-w-sm flex-col justify-center gap-8 px-4 py-10">
      <div className="space-y-4">
        <BrandMark size="lg" />
        <div className="space-y-0.5">
          {LANGUAGES.map((l, i) => (
            <p
              key={l.code}
              lang={l.code}
              className={`font-display tracking-tight ${i === 0 ? "text-3xl font-bold" : "text-xl font-semibold text-muted"}`}
            >
              {resources[l.code].translation.language.choose}
            </p>
          ))}
        </div>
      </div>
      <div className="overflow-hidden rounded-xl border border-line bg-surface">
        {LANGUAGES.map((l, i) => (
          <button
            key={l.code}
            type="button"
            lang={l.code}
            className={`group flex min-h-[64px] w-full items-center gap-4 px-4 text-left transition-colors hover:bg-sunken ${i ? "border-t border-line" : ""}`}
            onClick={() => setLanguage(l.code as LanguageCode)}
          >
            <span className="num w-6 text-xs font-semibold uppercase text-muted" aria-hidden>
              {l.code}
            </span>
            <span className="flex-1 font-display text-2xl font-semibold">
              {l.label}
              {l.code !== "en" && <span className="ml-2 text-sm font-normal text-muted">({l.english})</span>}
            </span>
            <span className="text-xl text-muted transition-transform group-hover:translate-x-0.5" aria-hidden>
              →
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
