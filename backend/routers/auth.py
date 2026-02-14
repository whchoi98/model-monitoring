"""Authentication router: login, register, approval, current user info."""

from __future__ import annotations

import logging
import threading

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import (
    ADMIN_EMAIL,
    PUBLIC_BASE_URL,
    hash_password,
    verify_password,
    create_access_token,
    create_approve_token,
    decode_approve_token,
    get_current_user,
)
from database import get_db
from models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=4, max_length=100)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=4, max_length=100)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UserResponse(BaseModel):
    id: int
    username: str
    approved: int = 0

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Email helper
# ---------------------------------------------------------------------------

def _send_approval_email(username: str, approve_url: str):
    """Send approval notification to admin via SES (fire-and-forget)."""
    def _send():
        try:
            ses = boto3.client("ses", region_name="us-east-1")
            ses.send_email(
                Source=ADMIN_EMAIL,
                Destination={"ToAddresses": [ADMIN_EMAIL]},
                Message={
                    "Subject": {"Data": f"[Bedrock Monitor] 회원가입 승인 요청: {username}", "Charset": "UTF-8"},
                    "Body": {
                        "Html": {
                            "Data": (
                                f"<h2>새 회원가입 승인 요청</h2>"
                                f"<p>아이디: <strong>{username}</strong></p>"
                                f"<p>아래 버튼을 클릭하면 해당 계정이 승인됩니다.</p>"
                                f'<p><a href="{approve_url}" style="display:inline-block;padding:12px 24px;'
                                f'background:#2563eb;color:#fff;text-decoration:none;border-radius:8px;'
                                f'font-weight:bold;">승인하기</a></p>'
                                f"<p style=\"color:#888;font-size:12px;\">이 링크는 7일간 유효합니다.</p>"
                            ),
                            "Charset": "UTF-8",
                        },
                    },
                },
            )
            logger.info("Approval email sent for user '%s'", username)
        except ClientError:
            logger.exception("Failed to send approval email for user '%s'", username)
        except Exception:
            logger.exception("Unexpected error sending approval email for user '%s'", username)

    threading.Thread(target=_send, daemon=True).start()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다",
        )

    if user.approved != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="계정 승인 대기 중입니다. 관리자 승인 후 이용 가능합니다.",
        )

    token = create_access_token(user.username)
    return TokenResponse(access_token=token, username=user.username)


@router.post("/register", response_model=UserResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == body.username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 존재하는 아이디입니다",
        )

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        approved=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Build approval URL and send email
    approve_token = create_approve_token(user.id)
    approve_url = f"{PUBLIC_BASE_URL}/api/auth/approve?token={approve_token}"
    _send_approval_email(user.username, approve_url)

    return user


@router.get("/approve", response_class=HTMLResponse)
def approve_user(token: str, db: Session = Depends(get_db)):
    """One-click approval link from email."""
    user_id = decode_approve_token(token)
    if user_id is None:
        return HTMLResponse(
            content=_result_html("승인 실패", "유효하지 않거나 만료된 링크입니다.", success=False),
            status_code=400,
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return HTMLResponse(
            content=_result_html("승인 실패", "사용자를 찾을 수 없습니다.", success=False),
            status_code=404,
        )

    if user.approved == 1:
        return HTMLResponse(
            content=_result_html("이미 승인됨", f"<strong>{user.username}</strong> 계정은 이미 승인되었습니다.", success=True),
        )

    user.approved = 1
    db.commit()
    logger.info("User '%s' (id=%d) approved via email link", user.username, user.id)

    return HTMLResponse(
        content=_result_html("승인 완료", f"<strong>{user.username}</strong> 계정이 승인되었습니다. 이제 로그인할 수 있습니다.", success=True),
    )


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return user


def _result_html(title: str, message: str, success: bool = True) -> str:
    color = "#10b981" if success else "#ef4444"
    icon = "&#10003;" if success else "&#10007;"
    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - Bedrock Monitor</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0a0a0a; color: #e5e5e5;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  .card {{ background: #111; border: 1px solid #333; border-radius: 16px; padding: 48px; text-align: center; max-width: 400px; }}
  .icon {{ font-size: 48px; color: {color}; margin-bottom: 16px; }}
  h1 {{ font-size: 24px; margin: 0 0 12px; }}
  p {{ color: #999; font-size: 14px; line-height: 1.6; }}
</style></head>
<body><div class="card">
  <div class="icon">{icon}</div>
  <h1>{title}</h1>
  <p>{message}</p>
</div></body></html>"""
