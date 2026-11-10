import { isLanguage, resources, type LanguageCode } from "@mandi/i18n";
import { ApiClient, type Meta } from "@mandi/shared";
import Constants from "expo-constants";
import i18n from "i18next";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { initReactI18next } from "react-i18next";
import { cacheJson, store } from "./store";

void i18n.use(initReactI18next).init({
  resources,
  lng: "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnObjects: true,
  compatibilityJSON: "v4",
});

const DEFAULT_API = (Constants.expoConfig?.extra?.apiBase as string | undefined) ?? "http://10.0.2.2:8000";

interface MobileState {
  api: ApiClient;
  meta: Meta | null;
  metaCached: boolean;
  language: LanguageCode | null;
  setLanguage: (l: LanguageCode) => void;
  autoSpeak: boolean;
  setAutoSpeak: (v: boolean) => void;
  keepRecordings: boolean;
  setKeepRecordings: (v: boolean) => void;
  apiBase: string;
  setApiBase: (url: string) => void;
  district: string | null;
  setDistrict: (d: string) => void;
}

const Ctx = createContext<MobileState | null>(null);

export function MobileProvider({ children }: { children: ReactNode }) {
  const [apiBase, setApiBaseState] = useState(() => store.get("mandi.apiBase") || DEFAULT_API);
  const api = useMemo(() => new ApiClient(apiBase, store), [apiBase]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaCached, setMetaCached] = useState(false);
  const [language, setLanguageState] = useState<LanguageCode | null>(() => {
    const saved = store.get("mandi.language");
    if (isLanguage(saved)) void i18n.changeLanguage(saved);
    return isLanguage(saved) ? saved : null;
  });
  const [autoSpeak, setAutoSpeakState] = useState(() => store.get("mandi.autoSpeak") !== "0");
  const [keepRecordings, setKeepRecordingsState] = useState(() => store.get("mandi.keepRecordings") === "1");
  const [district, setDistrictState] = useState<string | null>(() => store.get("mandi.district"));

  useEffect(() => {
    if (language) void i18n.changeLanguage(language);
  }, [language]);

  useEffect(() => {
    cacheJson("meta", () => api.meta())
      .then(({ data, cached }) => {
        setMeta(data);
        setMetaCached(cached);
      })
      .catch(() => setMeta(null));
  }, [api]);

  const setLanguage = useCallback((l: LanguageCode) => {
    store.set("mandi.language", l);
    void i18n.changeLanguage(l); // synchronous switch, so the header and tab bar update too
    setLanguageState(l);
  }, []);
  const setAutoSpeak = useCallback((v: boolean) => {
    store.set("mandi.autoSpeak", v ? "1" : "0");
    setAutoSpeakState(v);
  }, []);
  const setKeepRecordings = useCallback((v: boolean) => {
    store.set("mandi.keepRecordings", v ? "1" : "0");
    setKeepRecordingsState(v);
  }, []);
  const setApiBase = useCallback((url: string) => {
    store.set("mandi.apiBase", url);
    setApiBaseState(url);
  }, []);

  const setDistrict = useCallback((d: string) => {
    store.set("mandi.district", d);
    setDistrictState(d);
  }, []);

  return (
    <Ctx.Provider value={{ api, meta, metaCached, language, setLanguage, autoSpeak, setAutoSpeak, keepRecordings, setKeepRecordings, apiBase, setApiBase, district, setDistrict }}>
      {children}
    </Ctx.Provider>
  );
}

export function useMobile(): MobileState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useMobile outside MobileProvider");
  return v;
}
