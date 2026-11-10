import en from "./locales/en.json";
import hi from "./locales/hi.json";
import mr from "./locales/mr.json";

/** Translation resources shared by the web and mobile apps (i18next format). */
export const resources = {
  en: { translation: en },
  hi: { translation: hi },
  mr: { translation: mr },
} as const;

export type LanguageCode = keyof typeof resources;

/** Adding a language: add a locale JSON file here and on the backend (glossary + templates). */
export const LANGUAGES: { code: LanguageCode; label: string; english: string; speechLocale: string }[] = [
  { code: "en", label: "English", english: "English", speechLocale: "en-IN" },
  { code: "hi", label: "हिंदी", english: "Hindi", speechLocale: "hi-IN" },
  { code: "mr", label: "मराठी", english: "Marathi", speechLocale: "mr-IN" },
];

export function isLanguage(code: string | null | undefined): code is LanguageCode {
  return !!code && code in resources;
}

export function speechLocale(code: string): string {
  return LANGUAGES.find((l) => l.code === code)?.speechLocale ?? "en-IN";
}
