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
#
# connect_args (2026-07-08 커넥션 풀 고갈 장애 재발 방지):
#   - TCP keepalive: DB/네트워크가 커넥션을 조용히 끊어도 idle 30s + 10s×3 안에 클라이언트
#     recv()가 실패해 커넥션이 무효화·회수된다. 미설정 시 워커 스레드가 죽은 소켓에서 영원히
#     블록되어 풀이 영구 고갈된다 (pool_recycle/pre_ping은 체크아웃 중인 커넥션엔 무력).
#   - statement_timeout: 런타임 쿼리 상한 (기본 30s, DB_STATEMENT_TIMEOUT_MS로 조정).
#     lifespan 마이그레이션은 main.py에서 자체 SET statement_timeout을 따로 건다.
#   - connect_timeout: 커넥션 수립 자체의 상한.
# psycopg2(libpq) 전용 파라미터라 postgresql URL에만 적용한다.
_STATEMENT_TIMEOUT_MS = int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "30000"))

_PG_CONNECT_ARGS = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
    "connect_timeout": 10,
    "options": f"-c statement_timeout={_STATEMENT_TIMEOUT_MS}",
}

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_recycle=300,
    pool_timeout=10,
    connect_args=_PG_CONNECT_ARGS if DATABASE_URL.startswith("postgresql") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def create_tables():
    """Create all tables defined by ORM models."""
    from models import ProbeRun, ProbeResult, PromptSet, User, Insight, FeatureRun, FeatureResult  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
