"use client";

import type { ReactNode } from "react";
import type { Lang } from "@/lib/i18n";
import { LanguageProvider } from "@/lib/i18n-context";
import { AuthProvider } from "@/lib/auth-context";

export default function Providers({ children, initialLang }: { children: ReactNode; initialLang: Lang }) {
  return (
    <LanguageProvider initialLang={initialLang}>
      <AuthProvider>{children}</AuthProvider>
    </LanguageProvider>
  );
}
