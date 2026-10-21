"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useT } from "@/lib/i18n-context";
import Dialog from "./Dialog";
import type { NavItem } from "./AppHeader";

export default function QuickNavigation({ items }: { items: NavItem[] }) {
  const t = useT();
  const w = t.workspace;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const close = () => { setOpen(false); setQuery(""); };

  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== "k" || event.isComposing || event.repeat) return;
      if (document.querySelector("dialog[open]")) return;
      event.preventDefault();
      setOpen(true);
    };
    document.addEventListener("keydown", handle);
    return () => document.removeEventListener("keydown", handle);
  }, []);

  const normalized = query.trim().normalize("NFKC").toLowerCase();
  const results = items.filter((item) =>
    `${item.label} ${item.href ?? ""}`.normalize("NFKC").toLowerCase().includes(normalized));

  return (
    <>
      <button type="button" className="quick-navigation-trigger" aria-label={w.quickNavigation}
        aria-haspopup="dialog" onClick={() => setOpen(true)}>
        <svg aria-hidden="true" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4.5 4.5" />
        </svg>
        <span className="hidden lg:inline">{w.quickNavigation}</span>
        <kbd className="hidden xl:inline">⌘ / Ctrl K</kbd>
      </button>
      {open && (
        <Dialog title={w.quickNavigation} onClose={close} initialFocus={input} className="max-w-xl">
          <label className="block">
            <span className="ui-label mb-2 block">{w.searchPages}</span>
            <input ref={input} type="search" className="ui-input w-full" value={query}
              onChange={(event) => setQuery(event.target.value)} placeholder={w.searchPagesHint} />
          </label>
          <div className="max-h-[min(55dvh,28rem)] space-y-1 overflow-y-auto p-1">
            {results.map((item) => (
              <Link key={item.key} href={item.href ?? "/"} className="quick-navigation-result"
                aria-current={item.active ? "page" : undefined} onClick={() => { item.onClick?.(); close(); }}>
                <span>
                  <span className="block font-semibold text-gray-100">{item.label}</span>
                  {item.group && <span className="mt-0.5 block text-xs text-gray-500">{t.navigationGroups[item.group]}</span>}
                </span>
                <span aria-hidden="true" className="text-gray-500">↗</span>
              </Link>
            ))}
            {!results.length && <p role="status" className="py-8 text-center text-sm text-gray-500">{w.noPages}</p>}
          </div>
          <p className="text-xs text-gray-500">{w.navigationHint}</p>
        </Dialog>
      )}
    </>
  );
}
