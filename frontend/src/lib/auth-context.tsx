"use client";

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from "react";
import { fetchMe, getToken, setToken } from "./api";
import { ApiError } from "./http";
import type { AuthUser } from "./types";
import { useLang } from "./i18n-context";
import LoginForm from "@/components/LoginForm";

interface OpenLogin {
  (): void;
  (afterLogin: () => void): void;
}

interface AuthContextValue {
  user: AuthUser | null;
  checking: boolean;
  openLogin: OpenLogin;
  logout: () => void;
  error: "unavailable" | "storage" | null;
  retry: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** One session check and login dialog for every route and protected action. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const { lang } = useLang();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<AuthContextValue["error"]>(null);
  const [loginOpen, setLoginOpen] = useState(false);
  const request = useRef<AbortController | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const afterLogin = useRef<(() => void) | null>(null);

  const checkSession = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setError(null);
    let token: string | null;
    try {
      token = getToken();
    } catch {
      setError("storage");
      setChecking(false);
      return;
    }
    if (!token) {
      setUser(null);
      setChecking(false);
      return;
    }

    setChecking(true);
    try {
      const nextUser = await fetchMe(controller.signal);
      if (request.current === controller && !controller.signal.aborted) {
        setUser(nextUser);
      }
    } catch (cause) {
      if (request.current !== controller || controller.signal.aborted) return;
      if (cause instanceof ApiError && (cause.status === 401 || cause.status === 403)) {
        setUser(null);
        try {
          setToken(null);
        } catch {
          setError("storage");
        }
      } else {
        // An unavailable auth service does not invalidate a previously verified session.
        setError("unavailable");
      }
    } finally {
      if (request.current === controller && !controller.signal.aborted) {
        setChecking(false);
      }
    }
  }, []);

  const retry = useCallback(() => { void checkSession(); }, [checkSession]);

  useEffect(() => {
    const onAuthChange = () => { void checkSession(); };
    const onStorage = (event: StorageEvent) => {
      if (event.key !== "auth_token" && event.key !== null) return;
      try {
        // Update api.ts's in-memory token as well as this tab's shared context.
        setToken(event.key === null ? null : event.newValue);
      } catch {
        setError("storage");
      }
    };
    window.addEventListener("auth-changed", onAuthChange);
    window.addEventListener("storage", onStorage);
    void checkSession();
    return () => {
      request.current?.abort();
      window.removeEventListener("auth-changed", onAuthChange);
      window.removeEventListener("storage", onStorage);
    };
  }, [checkSession]);

  const openLogin: OpenLogin = useCallback((onSuccess?: () => void) => {
    afterLogin.current = typeof onSuccess === "function" ? onSuccess : null;
    setLoginOpen(true);
  }, []);

  const closeLogin = useCallback(() => {
    afterLogin.current = null;
    setLoginOpen(false);
  }, []);

  const logout = useCallback(() => {
    request.current?.abort();
    request.current = null;
    setUser(null);
    setChecking(false);
    setError(null);
    closeLogin();
    try {
      setToken(null);
    } catch {
      setError("storage");
    }
  }, [closeLogin]);

  useEffect(() => {
    const element = dialog.current;
    if (!loginOpen || !element) return;
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    if (!element.open) element.showModal();
    element.querySelector<HTMLInputElement>("input")?.focus();
    return () => {
      if (element.open) element.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) {
        previousFocus.focus();
      }
    };
  }, [loginOpen]);

  const onLoginSuccess = (username: string) => {
    // LoginForm has already verified the credentials and broadcast auth-changed.
    setUser({ id: 0, username });
    const resume = afterLogin.current;
    closeLogin();
    if (resume) window.setTimeout(resume, 0);
  };

  const value = useMemo(
    () => ({ user, checking, openLogin, logout, error, retry }),
    [user, checking, openLogin, logout, error, retry],
  );

  return (
    <AuthContext.Provider value={value}>
      {children}
      <dialog
        ref={dialog}
        tabIndex={-1}
        aria-label={lang === "en" ? "Login" : "로그인"}
        className="m-auto w-[calc(100%-2rem)] max-w-md max-h-[calc(100dvh-2rem)] overflow-y-auto rounded-xl border border-gray-800 bg-gray-950 p-0 text-gray-100 shadow-2xl backdrop:bg-black/60 backdrop:backdrop-blur-sm"
        onCancel={(event) => { event.preventDefault(); closeLogin(); }}
        onKeyDown={(event) => {
          if (event.key !== "Tab") return;
          const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
            'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])',
          )).filter((element) => element.getClientRects().length > 0);
          const first = controls[0];
          const last = controls[controls.length - 1];
          if (!first || !last) {
            event.preventDefault();
            event.currentTarget.focus();
          } else if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
        onClick={(event) => {
          if (event.target !== event.currentTarget) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          if (event.clientX < bounds.left || event.clientX > bounds.right
            || event.clientY < bounds.top || event.clientY > bounds.bottom) closeLogin();
        }}
      >
        <div className="sticky top-0 z-10 flex justify-end bg-gray-950 p-2">
          <button
            type="button"
            onClick={closeLogin}
            aria-label={lang === "en" ? "Close login" : "로그인 닫기"}
            className="flex h-10 w-10 items-center justify-center rounded-lg text-xl text-gray-400 hover:bg-gray-800 hover:text-gray-100"
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>
        {loginOpen && (
          <div className="[&>div]:py-0 [&>div>div]:max-w-none [&>div>div>div]:border-0 [&>div>div>div]:bg-transparent">
            <LoginForm onLoginSuccess={onLoginSuccess} />
          </div>
        )}
      </dialog>
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
