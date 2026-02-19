"use client";

import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { ko, en, Translations, Lang } from "./i18n";

const translations: Record<Lang, Translations> = { ko, en };

const LangContext = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({
  lang: "ko",
  setLang: () => {},
});

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("ko");

  useEffect(() => {
    const stored = localStorage.getItem("lang");
    if (stored === "en" || stored === "ko") {
      setLangState(stored);
    }
  }, []);

  const setLang = (l: Lang) => {
    setLangState(l);
    localStorage.setItem("lang", l);
  };

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
