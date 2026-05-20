"""SQLAlchemy engine + session factory.

DATABASE_URL 우선순위:
  1) `DATABASE_URL` 환경변수 직접 주입 (전체 URI).
  2) 그 외에는 ECS Task가 Secrets Manager / SSM으로 주입하는
     DB_USER / DB_PASSWORD / DB_HOST / DB_PORT / DB_NAME 조합.
  3) 모두 없을 때만 로컬 개발 fallback (postgres@localhost).

v2 ECS 배포 시 secrets에서 DB_* 5종을 주입한다.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger(__name__)


def _build_database_url() -> str:
    direct = os.environ.get("DATABASE_URL")
    if direct:
        return direct

    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    host = os.environ.get("DB_HOST")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "monitoring")

    if user and password and host:
        return (
            f"postgresql://{quote_plus(user)}:{quote_plus(password)}"
            f"@{host}:{port}/{name}"
        )

    # 로컬 개발 fallback - 운영 환경에서는 위 분기로 처리되어야 한다.
    logger.warning(
        "DATABASE_URL / DB_* env vars 미설정. 로컬 개발 기본값(postgres@localhost) 사용."
    )
    return "postgresql://postgres:postgres@localhost:5432/monitoring"


DATABASE_URL = _build_database_url()

# RDS t4g.micro max_connections ~85. backend task + scheduler tasks + DBA tools가 공유하므로
# 각 task pool은 작게 (5+5=10). pool_recycle로 stale connection 자동 회수.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_recycle=300,
    pool_timeout=10,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def create_tables():
    """Create all tables defined by ORM models."""
    from models import ProbeRun, ProbeResult, PromptSet, User, Insight  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
