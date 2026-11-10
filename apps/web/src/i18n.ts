import { isLanguage, resources } from "@mandi/i18n";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

function savedLanguage(): string {
  try {
    const saved = localStorage.getItem("mandi.language");
    return isLanguage(saved) ? saved : "en";
  } catch {
    return "en";
  }
}

// Start in the saved language so the first paint (header, tab bar) is already translated.
void i18n.use(initReactI18next).init({
  resources,
  lng: savedLanguage(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnObjects: true,
});

export default i18n;
