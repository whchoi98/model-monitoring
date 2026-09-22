"use client";

import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";
import { ko, en, Translations, Lang } from "./i18n";

const translations: Record<Lang, Translations> = { ko, en };

const LangContext = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({
  lang: "ko",
  setLang: () => {},
});

export function LanguageProvider({
  children,
  initialLang = "ko",
}: {
  children: ReactNode;
  initialLang?: Lang;
}) {
  const [lang, setLangState] = useState<Lang>(initialLang);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("lang");
      if (stored === "en" || stored === "ko") setLangState(stored);
    } catch {
      // The server cookie and in-memory selection still work without storage.
    }
    const onStorage = (event: StorageEvent) => {
      if (event.key === "lang" && (event.newValue === "en" || event.newValue === "ko")) {
        setLangState(event.newValue);
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
    try {
      document.cookie = `lang=${lang}; Path=/; Max-Age=31536000; SameSite=Lax`;
    } catch {
      // Cookie restrictions must not prevent a language change.
    }
  }, [lang]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem("lang", l);
    } catch {
      // Keep the current session usable when browser persistence is blocked.
    }
  }, []);

  return (
    <LangContext.Provider value={{ lang, setLang }}>
      {children}
    </LangContext.Provider>
  );
}

export function useT(): Translations {
  const { lang } = useContext(LangContext);
  return translations[lang];
}

export function useLang() {
  return useContext(LangContext);
}
