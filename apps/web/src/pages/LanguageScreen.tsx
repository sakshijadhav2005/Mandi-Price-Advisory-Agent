import { LANGUAGES, type LanguageCode } from "@mandi/i18n";
import { resources } from "@mandi/i18n";
import { useApp } from "../lib/app-context";

/** First-launch language picker. Shown in every language at once, since none is chosen yet. */
export function LanguageScreen() {
  const { setLanguage } = useApp();
  return (
    <div className="mx-auto flex min-h-[100dvh] max-w-sm flex-col justify-center gap-6 px-4">
      <div className="text-center">
        <div className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-leaf-600 text-2xl font-bold text-white" aria-hidden>
          ₹
        </div>
        {LANGUAGES.map((l) => (
          <p key={l.code} lang={l.code} className="text-lg font-semibold">
            {resources[l.code].translation.language.choose}
          </p>
        ))}
      </div>
      <div className="flex flex-col gap-3">
        {LANGUAGES.map((l) => (
          <button key={l.code} type="button" lang={l.code} className="btn-primary min-h-[60px] text-xl" onClick={() => setLanguage(l.code as LanguageCode)}>
            {l.label}
            {l.code !== "en" && <span className="text-sm font-normal opacity-80">({l.english})</span>}
          </button>
        ))}
      </div>
    </div>
  );
}
