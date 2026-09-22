"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { APP_VERSION } from "@/lib/version";
import { useT, useLang } from "@/lib/i18n-context";
import type { AuthUser } from "@/lib/types";
import ThemeToggle from "./ThemeToggle";

export interface NavItem {
  key: string;
  label: string;
  href?: string;
  onClick?: () => void;
  active?: boolean;
}

export function useNavItems(currentKey: string): NavItem[] {
  const t = useT();
  const { lang } = useLang();
  const L = (en: string, ko: string) => lang === "en" ? en : ko;
  const items: NavItem[] = [
    { key: "dashboard", label: t.dashboardTab, href: "/" },
    { key: "models", label: L("Models", "모델 탐색"), href: "/models" },
    { key: "parity", label: L("Parity Run", "패리티 런"), href: "/parity" },
    { key: "cost", label: L("Cost", "비용"), href: "/cost" },
    { key: "reliability", label: L("Reliability", "신뢰성"), href: "/reliability" },
    { key: "efficiency", label: L("Efficiency", "효율성"), href: "/efficiency" },
    { key: "analysis", label: L("Analysis", "분석"), href: "/analysis" },
    { key: "gptbench", label: "GPT on AWS", href: "/gpt-on-aws" },
    { key: "features", label: L("Claude API Features", "Claude API 기능"), href: "/claude-features" },
    { key: "manual", label: t.manualProbeTab, href: "/?view=manual" },
    { key: "prompts", label: L("Prompts", "프롬프트"), href: "/prompts" },
  ];
  return items.map((item) => ({ ...item, active: item.key === currentKey }));
}

function NavEntry({ item, mobile, onNavigate }: { item: NavItem; mobile?: boolean; onNavigate: () => void }) {
  const cls = `flex min-h-10 items-center rounded-md px-3 py-2 text-sm font-medium transition-colors ${
    mobile ? "w-full text-left" : "shrink-0 whitespace-nowrap"
  } ${item.active ? "bg-blue-600 text-white" : "text-gray-400 hover:bg-gray-800 hover:text-gray-100"}`;
  if (item.onClick) {
    return (
      <button type="button" aria-current={item.active ? "page" : undefined}
        onClick={() => { item.onClick?.(); onNavigate(); }} className={cls}>
        {item.label}
      </button>
    );
  }
  return (
    <Link href={item.href ?? "/"} onClick={onNavigate} className={cls}
      aria-current={item.active ? "page" : undefined}>
      {item.label}
    </Link>
  );
}

function Preferences() {
  const { lang, setLang } = useLang();
  return (
    <div className="flex items-center gap-1 rounded-lg bg-gray-800/50 p-1">
      {(["ko", "en"] as const).map((language) => (
        <button
          key={language} type="button" lang={language}
          aria-label={language === "ko" ? "한국어" : "English"}
          aria-pressed={lang === language}
          onClick={() => setLang(language)}
          className={`min-h-9 rounded-md px-2.5 text-xs font-medium ${
            lang === language ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-100"
          }`}
        >
          {language.toUpperCase()}
        </button>
      ))}
      <ThemeToggle />
    </div>
  );
}

export default function AppHeader({
  items, user, checking = false, onLoginClick, onLogout, actions,
}: {
  items: NavItem[];
  user: AuthUser | null;
  checking?: boolean;
  onLoginClick: () => void;
  onLogout: () => void;
  actions?: ReactNode;
}) {
  const t = useT();
  const { lang } = useLang();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuId = useId();
  const header = useRef<HTMLElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const desktopNav = useRef<HTMLElement>(null);
  const activeKey = items.find((item) => item.active)?.key;
  const close = () => setMenuOpen(false);

  useEffect(() => {
    setMenuOpen(false);
    desktopNav.current?.querySelector<HTMLElement>('[aria-current="page"]')
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [activeKey]);

  useEffect(() => {
    const element = header.current;
    if (!element) return;
    const measure = () => document.documentElement.style.setProperty(
      "--app-header-height", `${element.getBoundingClientRect().height}px`,
    );
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector("dialog[open]")) {
        event.preventDefault();
        setMenuOpen(false);
        toggle.current?.focus();
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && !header.current?.contains(event.target)) setMenuOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [menuOpen]);

  return (
    <header ref={header} className="sticky top-0 z-40 min-w-0 border-b border-gray-800 bg-gray-950/95 backdrop-blur">
      <div className="flex min-h-16 items-center justify-between gap-3 px-4 py-2 sm:px-6">
        <Link href="/" aria-label="LLM Monitor" title={t.appTitle} className="flex min-w-0 items-center gap-2.5 text-gray-100">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-600">
            <svg aria-hidden="true" className="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </span>
          <span className="whitespace-nowrap text-base font-bold sm:text-lg">LLM Monitor</span>
          <span className="hidden text-xs font-normal text-gray-500 xl:inline">{APP_VERSION}</span>
        </Link>
        <div className="flex shrink-0 items-center gap-2 sm:gap-3">
          <div className="hidden md:block"><Preferences /></div>
          {actions && <div className="hidden items-center gap-2 md:flex">{actions}</div>}
          {user ? (
            <div className="flex items-center gap-2">
              <span className="hidden max-w-40 truncate text-xs text-gray-400 sm:inline" title={user.username}>{user.username}</span>
              <button type="button" onClick={onLogout}
                className="min-h-10 rounded-lg bg-gray-800 px-3 text-xs font-medium text-gray-300 hover:bg-gray-700">
                {t.logout}
              </button>
            </div>
          ) : (
            <button type="button" onClick={() => { close(); onLoginClick(); }} disabled={checking}
              aria-busy={checking}
              className="min-h-10 rounded-lg bg-blue-600 px-3 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-60">
              {checking ? (lang === "en" ? "Checking…" : "확인 중…") : (lang === "en" ? "Login" : "로그인")}
            </button>
          )}
          <button ref={toggle} type="button" onClick={() => setMenuOpen((open) => !open)}
            className="flex h-10 w-10 items-center justify-center rounded-lg bg-gray-800 text-gray-300 md:hidden"
            aria-label={lang === "en" ? (menuOpen ? "Close navigation" : "Open navigation") : (menuOpen ? "메뉴 닫기" : "메뉴 열기")}
            aria-expanded={menuOpen} aria-controls={menuId}>
            <svg aria-hidden="true" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d={menuOpen ? "M6 18L18 6M6 6l12 12" : "M4 6h16M4 12h16M4 18h16"} />
            </svg>
          </button>
        </div>
      </div>
      <nav ref={desktopNav} aria-label={lang === "en" ? "Primary navigation" : "주요 메뉴"}
        className="hidden max-w-full overflow-x-auto border-t border-gray-800/60 md:block">
        <div className="flex w-max min-w-full items-center gap-1 px-4 py-1.5 sm:px-6">
          {items.map((item) => <NavEntry key={item.key} item={item} onNavigate={close} />)}
        </div>
      </nav>
      <nav id={menuId} hidden={!menuOpen} aria-label={lang === "en" ? "Mobile navigation" : "모바일 메뉴"}
        className="max-h-[calc(100dvh-4rem)] overflow-y-auto border-t border-gray-800 px-4 py-3 md:hidden">
        <div className="space-y-1">
          {items.map((item) => <NavEntry key={item.key} item={item} mobile onNavigate={close} />)}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-gray-800 pt-3">
          <Preferences />
          {actions}
        </div>
      </nav>
    </header>
  );
}
