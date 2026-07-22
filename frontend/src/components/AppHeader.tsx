"use client";

// 공용 헤더 (v2.16.0) — 9개 페이지의 중복 헤더를 대체.
// 데스크톱(lg+): 가로 내비. 모바일: 햄버거(☰) → 세로 드롭다운.
// 내비 항목은 데이터(NavItem)로 받아 대시보드의 상태형 탭(onClick)과
// 서브페이지의 링크형(href)을 동일하게 렌더링한다.

import { ReactNode, useState } from "react";
import Link from "next/link";
import { APP_VERSION } from "@/lib/version";
import { useT, useLang } from "@/lib/i18n-context";
import { AuthUser } from "@/lib/types";
import ThemeToggle from "./ThemeToggle";

export interface NavItem {
  key: string;
  label: string;
  href?: string;
  onClick?: () => void;
  active?: boolean;
}

/** 표준 10개 내비 항목 — currentKey 항목에 active 표시. 페이지에서 필요 시 항목을 덮어쓴다. */
export function useNavItems(currentKey: string): NavItem[] {
  const t = useT();
  const { lang } = useLang();
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  // 공개 메뉴 먼저, 로그인 필요 메뉴(수동 프로브·프롬프트)는 맨 뒤 (v2.16.1)
  const items: NavItem[] = [
    { key: "dashboard", label: t.dashboardTab, href: "/" },
    { key: "models", label: L("Models", "모델 탐색"), href: "/models" },
    { key: "parity", label: L("Parity Run", "패리티 런"), href: "/parity" },
    { key: "cost", label: L("Cost", "비용"), href: "/cost" },
    { key: "reliability", label: L("Reliability", "신뢰성"), href: "/reliability" },
    { key: "efficiency", label: L("Efficiency", "효율성"), href: "/efficiency" },
    { key: "analysis", label: L("Analysis", "분석"), href: "/analysis" },
    { key: "gptbench", label: "GPT on AWS", href: "/gpt-on-aws" },
    { key: "manual", label: t.manualProbeTab, href: "/" },
    { key: "prompts", label: L("Prompts", "프롬프트"), href: "/prompts" },
  ];
  return items.map((i) => ({ ...i, active: i.key === currentKey }));
}

function NavEntry({ item, mobile, onNavigate }: { item: NavItem; mobile?: boolean; onNavigate: () => void }) {
  const base = mobile
    ? "block w-full text-left px-4 py-2.5 text-sm font-medium rounded-lg transition-colors"
    : "px-4 py-1.5 text-sm font-medium rounded-md transition-colors whitespace-nowrap";
  const cls = `${base} ${item.active ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-200"}`;
  if (item.onClick) {
    return (
      <button type="button" onClick={() => { item.onClick?.(); onNavigate(); }} className={cls}>
        {item.label}
      </button>
    );
  }
  return (
    <Link href={item.href ?? "/"} onClick={onNavigate} className={cls}>
      {item.label}
    </Link>
  );
}

export default function AppHeader({
  items,
  user,
  onLoginClick,
  onLogout,
  actions,
}: {
  items: NavItem[];
  user: AuthUser | null;
  onLoginClick: () => void;
  onLogout: () => void;
  actions?: ReactNode;
}) {
  const t = useT();
  const { lang, setLang } = useLang();
  const [menuOpen, setMenuOpen] = useState(false);
  const close = () => setMenuOpen(false);

  return (
    <header className="sticky top-0 z-40 bg-gray-950/90 backdrop-blur border-b border-gray-800">
      <div className="flex items-center justify-between px-4 sm:px-6 py-3 gap-2">
        {/* 로고 + 제목 (모바일에선 설명·버전 숨김) */}
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center shrink-0">
            <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div className="min-w-0">
            <h1 className="text-base sm:text-lg font-bold text-gray-100 truncate">{t.appTitle}</h1>
            <p className="text-xs text-gray-500 hidden sm:block">{t.appDesc}</p>
            <span className="text-[10px] text-gray-600 font-mono tabular-nums hidden sm:inline">{APP_VERSION}</span>
          </div>
        </div>

        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          {/* 언어/테마 */}
          <div className="flex bg-gray-800/50 rounded-lg p-0.5">
            <button
              onClick={() => setLang("ko")}
              className={`px-2 py-1 text-xs font-medium rounded-md transition-colors ${lang === "ko" ? "bg-gray-600 text-white" : "text-gray-400 hover:text-gray-200"}`}
            >
              KO
            </button>
            <button
              onClick={() => setLang("en")}
              className={`px-2 py-1 text-xs font-medium rounded-md transition-colors ${lang === "en" ? "bg-gray-600 text-white" : "text-gray-400 hover:text-gray-200"}`}
            >
              EN
            </button>
            <ThemeToggle />
          </div>

          {/* 데스크톱 내비 (lg 이상) */}
          <nav className="hidden lg:flex bg-gray-800/50 rounded-lg p-0.5">
            {items.map((item) => (
              <NavEntry key={item.key} item={item} onNavigate={close} />
            ))}
          </nav>

          {/* 로그인/로그아웃 */}
          {user ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400 hidden sm:inline">{user.username}</span>
              <button
                onClick={onLogout}
                className="px-3 py-1.5 text-xs font-medium text-gray-400 hover:text-gray-200 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
              >
                {t.logout}
              </button>
            </div>
          ) : (
            <button
              onClick={onLoginClick}
              className="px-3 py-1.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors"
            >
              {lang === "en" ? "Login" : "로그인"}
            </button>
          )}

          {/* 페이지별 추가 버튼 (모바일에선 드롭다운으로 이동) */}
          {actions && <div className="hidden sm:flex items-center gap-2">{actions}</div>}

          {/* 햄버거 (lg 미만) */}
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            className="lg:hidden p-2 rounded-lg bg-gray-800/50 text-gray-300 hover:text-white"
            aria-label={menuOpen ? "close menu" : "open menu"}
            aria-expanded={menuOpen}
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              {menuOpen ? (
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
              )}
            </svg>
          </button>
        </div>
      </div>

      {/* 모바일 드롭다운 메뉴 */}
      {menuOpen && (
        <nav className="lg:hidden border-t border-gray-800 px-4 py-3 space-y-1 bg-gray-950/95 light:bg-white">
          {items.map((item) => (
            <NavEntry key={item.key} item={item} mobile onNavigate={close} />
          ))}
          {actions && <div className="pt-2 border-t border-gray-800 flex items-center gap-2 sm:hidden">{actions}</div>}
        </nav>
      )}
    </header>
  );
}
