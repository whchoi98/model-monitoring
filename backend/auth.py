"""Authentication utilities: password hashing and JWT token management."""

import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models import User

_INSECURE_PLACEHOLDERS = {
    "bedrock-monitor-secret-change-me",
    "placeholder-replace-with-secure-string-after-deploy",
    "",
}

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "")
if SECRET_KEY in _INSECURE_PLACEHOLDERS or len(SECRET_KEY) < 32:
    # 운영 환경에서 publicly-known key로 토큰을 서명하지 않도록 즉시 실패한다.
    # ECS Task가 SSM SecureString을 주입하지 않으면 (예: 권한 누락) 여기서 멈춤.
    raise RuntimeError(
        "JWT_SECRET_KEY env var가 안전한 값으로 설정되지 않았습니다. "
        "최소 32자 이상이며 placeholder가 아닌 값을 SSM SecureString으로 주입하세요."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)
security = HTTPBearer(auto_error=False)

ADMIN_EMAIL = "whchoi98@gmail.com"
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://d1ra694ytoup3r.cloudfront.net")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": username, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def create_approve_token(user_id: int) -> str:
    """Create a signed token for one-click email approval (7 days validity)."""
    expire = datetime.now(timezone.utc) + timedelta(days=7)
    return jwt.encode({"approve_user_id": user_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def decode_approve_token(token: str) -> Optional[int]:
    """Decode an approval token and return user_id, or None if invalid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("approve_user_id")
    except JWTError:
        return None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency: extract and validate JWT, return the User object."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="인증이 필요합니다")

    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 토큰입니다")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 토큰입니다")

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="사용자를 찾을 수 없습니다")
    if user.approved != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="계정 승인 대기 중입니다. 관리자 승인 후 이용 가능합니다.")
    return user
