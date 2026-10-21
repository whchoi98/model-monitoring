"""Public aggregate reads and same-origin, signed-cookie browser heartbeats."""

import hashlib
import hmac
import logging
import os
import re
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth import SECRET_KEY
from database import get_db
import presence as store

router = APIRouter(prefix="/api/presence", tags=["presence"])
logger = logging.getLogger(__name__)
COOKIE_NAME = "llm_monitor_visitor"
COOKIE_PATTERN = re.compile(r"^([0-9a-f]{32})\.([0-9a-f]{64})$")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class HeartbeatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _signature(visitor: str) -> str:
    return hmac.new(SECRET_KEY.encode(), f"llm-monitor:visitor-cookie:v1\0{visitor}".encode(), hashlib.sha256).hexdigest()


def _visitor(request: Request) -> str | None:
    match = COOKIE_PATTERN.fullmatch(request.cookies.get(COOKIE_NAME, ""))
    if match and hmac.compare_digest(match[2], _signature(match[1])):
        return match[1]
    return None


def _origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            return None
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            return None
        host = parsed.hostname.lower()
        host = f"[{host}]" if ":" in host else host
        port = parsed.port
        suffix = "" if port is None or port == (443 if parsed.scheme == "https" else 80) else f":{port}"
        return f"{parsed.scheme}://{host}{suffix}"
    except ValueError:
        return None


def _same_origin(request: Request) -> bool:
    origin = _origin(request.headers.get("origin", ""))
    if not origin or request.headers.get("x-llm-monitor-client") != "1":
        return False
    configured = os.environ.get("PRESENCE_ALLOWED_ORIGINS")
    if configured:
        return origin in {_origin(value.strip()) for value in configured.split(",")}
    public = _origin(os.environ.get("PUBLIC_BASE_URL", ""))
    if public:
        return origin == public
    # Local Next.js rewrites can use a different backend port.
    if request.url.hostname in LOCAL_HOSTS:
        return urlsplit(origin).hostname in LOCAL_HOSTS
    return origin == _origin(str(request.base_url))


def _unavailable(db: Session) -> HTTPException:
    db.rollback()
    return HTTPException(
        status_code=503, detail="접속 집계를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        headers={"Cache-Control": "no-store", "Retry-After": "5"},
    )


@router.get("")
def read_presence(request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    try:
        result = store.snapshot(db)
    except (SQLAlchemyError, ValueError):
        logger.warning("Presence read unavailable")
        raise _unavailable(db) from None
    if not _visitor(request):
        visitor = uuid.uuid4().hex
        response.set_cookie(
            COOKIE_NAME, f"{visitor}.{_signature(visitor)}",
            max_age=365 * 24 * 60 * 60, httponly=True, samesite="lax", path="/api/presence",
            secure=request.url.scheme == "https" or request.url.hostname not in LOCAL_HOSTS,
        )
    return result


@router.post("")
def record_presence(body: HeartbeatBody, request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    if not _same_origin(request):
        raise HTTPException(status_code=403, detail="같은 사이트의 방문 확인 요청만 허용합니다.")
    visitor = _visitor(request)
    if visitor is None:
        raise HTTPException(status_code=401, detail="방문자 쿠키를 먼저 확인해 주세요.")
    try:
        return store.heartbeat(db, visitor)
    except (SQLAlchemyError, ValueError):
        logger.warning("Presence heartbeat unavailable")
        raise _unavailable(db) from None
