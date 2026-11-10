import { ApiClient, type KeyValueStore, type Meta } from "@mandi/shared";
import { isLanguage, type LanguageCode } from "@mandi/i18n";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import i18n from "../i18n";

/** localStorage wrapper that never throws (private mode, blocked storage). */
export const webStore: KeyValueStore = {
  get(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* ignore */
    }
  },
  remove(key) {
    try {
      localStorage.removeItem(key);
    } catch {
      /* ignore */
    }
  },
};

const DEFAULT_API = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

interface AppState {
  api: ApiClient;
  meta: Meta | null;
  metaError: string | null;
  language: LanguageCode | null;
  setLanguage: (lang: LanguageCode) => void;
  autoSpeak: boolean;
  setAutoSpeak: (v: boolean) => void;
  apiBase: string;
  setApiBase: (url: string) => void;
  district: string | null;
  setDistrict: (d: string | null) => void;
  loggedIn: boolean;
  logout: () => void;
  refreshAuth: () => void;
}

const Ctx = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [apiBase, setApiBaseState] = useState(() => webStore.get("mandi.apiBase") || DEFAULT_API);
  const api = useMemo(() => new ApiClient(apiBase, webStore), [apiBase]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [language, setLanguageState] = useState<LanguageCode | null>(() => {
    const saved = webStore.get("mandi.language");
    return isLanguage(saved) ? saved : null;
  });
  const [autoSpeak, setAutoSpeakState] = useState(() => webStore.get("mandi.autoSpeak") === "1");
  const [loggedIn, setLoggedIn] = useState(() => !!api.token);
  const [district, setDistrictState] = useState<string | null>(() => webStore.get("mandi.district"));

  useEffect(() => {
    if (language) {
      void i18n.changeLanguage(language);
      document.documentElement.lang = language;
    }
  }, [language]);

  useEffect(() => {
    setMeta(null);
    setMetaError(null);
    api
      .meta()
      .then(setMeta)
      .catch((e: Error) => setMetaError(e.message));
  }, [api]);

  const setLanguage = useCallback((lang: LanguageCode) => {
    webStore.set("mandi.language", lang);
    // Switch synchronously (resources are bundled), before the next render. Switching in an
    // effect left always-mounted components such as the header and tab bar in the old language.
    void i18n.changeLanguage(lang);
    document.documentElement.lang = lang;
    setLanguageState(lang);
  }, []);
  const setAutoSpeak = useCallback((v: boolean) => {
    webStore.set("mandi.autoSpeak", v ? "1" : "0");
    setAutoSpeakState(v);
  }, []);
  const setApiBase = useCallback((url: string) => {
    webStore.set("mandi.apiBase", url);
    setApiBaseState(url);
  }, []);
  const logout = useCallback(() => {
    api.setToken(null);
    setLoggedIn(false);
  }, [api]);
  const refreshAuth = useCallback(() => setLoggedIn(!!api.token), [api]);
  const setDistrict = useCallback((d: string | null) => {
    if (d) webStore.set("mandi.district", d);
    else webStore.remove("mandi.district");
    setDistrictState(d);
  }, []);

  const value = {
    api, meta, metaError, language, setLanguage, autoSpeak, setAutoSpeak, apiBase, setApiBase,
    loggedIn, logout, refreshAuth, district, setDistrict,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside AppProvider");
  return v;
}
