"""Signed browser identity and bounded admission for public AI conversations."""

from collections import deque
import hashlib
import hmac
import os
import re
from threading import Lock
from time import monotonic
import uuid
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response

from auth import SECRET_KEY

COOKIE_NAME = "llm_monitor_chat"
_COOKIE = re.compile(r"^([0-9a-f]{32})\.([0-9a-f]{64})$")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _signature(browser: str) -> str:
    return hmac.new(SECRET_KEY.encode(), f"llm-monitor:chat-browser:v1\0{browser}".encode(), hashlib.sha256).hexdigest()


def guest_identity(request: Request) -> tuple[str, str | None]:
    match = _COOKIE.fullmatch(request.cookies.get(COOKIE_NAME, ""))
    if match and hmac.compare_digest(match[2], _signature(match[1])):
        browser, cookie = match[1], None
    else:
        browser = uuid.uuid4().hex
        cookie = f"{browser}.{_signature(browser)}"
    actor = hashlib.sha256(f"llm-monitor:chat-guest:v1\0{browser}".encode()).hexdigest()
    return f"guest-{actor}", cookie


def member_actor(username: str) -> str:
    # Account names can contain @ and .; AgentCore actor IDs cannot.
    return "user-" + hashlib.sha256(username.encode()).hexdigest()


def set_guest_cookie(response: Response, request: Request, value: str) -> None:
    response.set_cookie(
        COOKIE_NAME, value, max_age=30 * 24 * 60 * 60, httponly=True, samesite="lax", path="/api/chat",
        secure=request.url.scheme == "https" or request.url.hostname not in _LOCAL_HOSTS,
    )


class GuestChatLimiter:
    """Per-process burst protection; bounded to at most 30 recent admissions."""

    def __init__(self) -> None:
        self._recent: deque[tuple[float, str]] = deque()
        self._lock = Lock()

    def admit(self, actor: str) -> None:
        now = monotonic()
        with self._lock:
            while self._recent and self._recent[0][0] <= now - 60:
                self._recent.popleft()
            if len(self._recent) >= 30 or sum(key == actor for _, key in self._recent) >= 6:
                raise HTTPException(
                    status_code=429,
                    detail="질문이 많습니다. 잠시 후 다시 시도해 주세요. Please wait a minute before trying again.",
                    headers={"Retry-After": "60", "Cache-Control": "no-store"},
                )
            self._recent.append((now, actor))


def check_browser_origin(request: Request) -> None:
    """Browser callers use this site's aliases; non-browser API clients send no Origin."""
    origin = request.headers.get("origin")
    if origin is None:
        return
    configured = (os.environ.get("CHAT_ALLOWED_ORIGINS") or os.environ.get("PRESENCE_ALLOWED_ORIGINS")
                  or os.environ.get("PUBLIC_BASE_URL"))
    if configured:
        allowed = {value.strip().rstrip("/") for value in configured.split(",")}
    else:
        allowed = {str(request.base_url).rstrip("/")}
        if request.url.hostname in _LOCAL_HOSTS:
            try:
                local = urlsplit(origin)
                if local.scheme in ("http", "https") and local.hostname in _LOCAL_HOSTS:
                    return
            except ValueError:
                pass
    if origin.rstrip("/") not in allowed:
        raise HTTPException(status_code=403, detail="이 사이트에서 챗봇을 열어 주세요. Open the chatbot on this site.")
