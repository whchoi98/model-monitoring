"""FastAPI application entry point for the Bedrock LLM Model Monitoring Tool."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from database import create_tables, engine, SessionLocal
from routers import models, probes, prompts, results
from routers import auto_probe
from routers import admin as admin_router
from routers import auth as auth_router
from routers import chat as chat_router
from routers import insights as insights_router
from routers import compare as compare_router
from routers import cost as cost_router
from routers import reliability as reliability_router
from routers import efficiency as efficiency_router
from routers import analysis as analysis_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: run startup tasks before yielding, cleanup after.

    v2: 데몬 스레드 auto-prober는 EventBridge Scheduler + Fargate Task로 분리되어
    여기서 시작하지 않는다. /api/auto-probe/trigger는 수동 호출시 in-process 실행.
    """
    logger.info("Creating database tables...")
    create_tables()

    # Migrations - advisory lock으로 동시 deploy 시 lock 경합 회피.
    # 두 task가 rolling 중 lifespan에서 동일 UPDATE/DELETE를 동시 실행하면 row lock 무한 대기 가능.
    # pg_advisory_lock(N)으로 한 번에 한 task만 마이그레이션 실행하도록 serialize.
    # 마이그레이션은 try/except로 감싸 backend startup이 절대 hang되지 않도록 보호.
    # statement_timeout으로 개별 쿼리 최대 30초 제한.
    # 실패해도 backend는 시작 — 마이그레이션은 다음 배포 또는 수동으로 retry.
    # 별도 short-lived connection으로 마이그레이션 실행.
    # engine.connect()의 pool connection을 사용하면 leak 가능 → 별도 raw 연결 권장.
    # 그러나 raw psycopg2 import 회피를 위해 dispose 패턴 사용.
    try:
        with engine.begin() as conn:  # begin은 commit/rollback 자동 + 연결 항상 반환
            conn.execute(text("SET statement_timeout = '30000'"))
            conn.execute(text("SELECT pg_advisory_lock(917350001)"))
            try:
                conn.execute(text("ALTER TABLE probe_runs ADD COLUMN IF NOT EXISTS is_auto INTEGER DEFAULT 0"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS approved INTEGER DEFAULT 0"))
                conn.execute(text("ALTER TABLE insights ADD COLUMN IF NOT EXISTS summary_md_en TEXT"))
                # Phase 3 Workload Preset
                conn.execute(text("ALTER TABLE probe_results ADD COLUMN IF NOT EXISTS category TEXT"))
                # Output Analysis (stop_reason 분포 + output 길이 통계)
                conn.execute(text("ALTER TABLE probe_results ADD COLUMN IF NOT EXISTS stop_reason TEXT"))
                # 2026-07-08 성능: trend/latest 풀 스캔 제거용 인덱스 (models.py 선언과 동기).
                # 최상단 `from routers import models`와 이름 충돌하므로 지점 import.
                from models import ensure_performance_indexes

                ensure_performance_indexes(conn)
                # 2026-05-20: 사용자 요청으로 Opus 4.5 + Sonnet 4.5를 모니터링 대상에서 제외 — 옛 row 삭제.
                conn.execute(text("DELETE FROM probe_results WHERE model_name LIKE '%Opus 4.5%'"))
                conn.execute(text("DELETE FROM probe_results WHERE model_name LIKE '%Sonnet 4.5%'"))
                _label_renames = [
                    ("Claude Opus 4.7 (Global)", "Bedrock Claude Opus 4.7 (Global)"),
                    ("Claude Opus 4.6 (Global)", "Bedrock Claude Opus 4.6 (Global)"),
                    ("Claude Sonnet 4.6 (Global)", "Bedrock Claude Sonnet 4.6 (Global)"),
                    ("Claude Haiku 4.5 (Global)", "Bedrock Claude Haiku 4.5 (Global)"),
                    ("Claude Opus 4.7 (US)", "Bedrock Claude Opus 4.7 (US)"),
                    ("Claude Opus 4.6 (US)", "Bedrock Claude Opus 4.6 (US)"),
                    ("Claude Sonnet 4.6 (US)", "Bedrock Claude Sonnet 4.6 (US)"),
                    ("Claude Haiku 4.5 (US)", "Bedrock Claude Haiku 4.5 (US)"),
                    ("Nova 2.0 Lite (US)", "Bedrock Nova 2.0 Lite (US)"),
                    ("Claude Opus 4.7 (US, 1P)", "Bedrock Claude Opus 4.7 (US)"),
                    ("Claude Opus 4.6 (US, 1P)", "Bedrock Claude Opus 4.6 (US)"),
                    ("Claude Sonnet 4.6 (US, 1P)", "Bedrock Claude Sonnet 4.6 (US)"),
                    ("Claude Haiku 4.5 (US, 1P)", "Bedrock Claude Haiku 4.5 (US)"),
                    ("Nova Lite (US, 1P)", "Bedrock Nova Lite (US)"),
                    ("Nova 2.0 Lite (US, 1P)", "Bedrock Nova 2.0 Lite (US)"),
                    ("Claude Opus 4.7 (CP on AWS)", "Anthropic Claude Opus 4.7 (US)"),
                    ("Claude Sonnet 4.6 (CP on AWS)", "Anthropic Claude Sonnet 4.6 (US)"),
                    ("Claude Haiku 4.5 (CP on AWS)", "Anthropic Claude Haiku 4.5 (US)"),
                    ("Claude Opus 4.7 (Anthropic API)", "Anthropic Claude Opus 4.7 (US)"),
                    ("Claude Sonnet 4.6 (Anthropic API)", "Anthropic Claude Sonnet 4.6 (US)"),
                    ("Claude Haiku 4.5 (Anthropic API)", "Anthropic Claude Haiku 4.5 (US)"),
                ]
                for old_name, new_name in _label_renames:
                    conn.execute(
                        text("UPDATE probe_results SET model_name = :new WHERE model_name = :old"),
                        {"new": new_name, "old": old_name},
                    )
                for removed in (
                    "Nova Pro (US, 1P)", "Bedrock Nova Pro (US)",
                    "Nova Lite (US, 1P)", "Bedrock Nova Lite (US)",
                    "Nova 2.0 Lite (Global)", "Bedrock Nova 2.0 Lite (Global)",
                ):
                    conn.execute(
                        text("DELETE FROM probe_results WHERE model_name = :n"),
                        {"n": removed},
                    )
                # engine.begin()이 자동 commit하므로 explicit commit 불필요
            finally:
                # advisory_unlock은 connection이 죽으면 자동 해제됨 — 실패해도 무시
                try:
                    conn.execute(text("SELECT pg_advisory_unlock(917350001)"))
                except Exception:
                    pass
    except Exception:
        logger.exception("Migration block failed (non-fatal, backend continues)")

    # Seed default admin user if no users exist
    _seed_default_admin()

    # Anthropic 직접 API 모델 자동 발견 (ANTHROPIC_API_KEY 설정 시에만 동작)
    try:
        from prober import _discover_anthropic_models, _register_openai_models
        _discover_anthropic_models()
        _register_openai_models()
    except Exception:
        logger.exception("Model discovery/registration failed (non-fatal)")

    logger.info("Database tables ready.")

    yield


def _seed_default_admin():
    """Create a default admin user if the users table is empty.

    Password는 SEED_ADMIN_PASSWORD 환경변수에서만 읽는다 (SSM SecureString 권장).
    환경변수가 없거나 너무 짧으면 시드 자체를 skip하고 운영자가 수동으로 사용자를
    추가하도록 한다. 절대로 코드에 평문 비밀번호를 두지 않는다.
    """
    import os
    from auth import hash_password
    from models import User

    seed_password = os.environ.get("SEED_ADMIN_PASSWORD", "").strip()
    seed_username = os.environ.get("SEED_ADMIN_USERNAME", "admin").strip()

    if len(seed_password) < 8:
        logger.warning(
            "SEED_ADMIN_PASSWORD 미설정 또는 8자 미만 - admin 시드 skip. "
            "운영자가 SSM SecureString에 충분히 강한 비밀번호를 설정해야 합니다."
        )
        return

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == seed_username).first()
        if existing is None:
            admin = User(
                username=seed_username,
                password_hash=hash_password(seed_password),
                approved=1,
            )
            db.add(admin)
            db.commit()
            logger.info("Default admin user '%s' created from env vars.", seed_username)
        else:
            # idempotent: env가 진실의 원천. 이전 비밀번호(예: v1 하드코딩 잔재) 위에 덮어쓴다.
            existing.password_hash = hash_password(seed_password)
            existing.approved = 1
            db.commit()
            logger.info("Default admin user '%s' password rotated from env vars.", seed_username)
    except Exception:
        logger.exception("Failed to seed default admin user")
    finally:
        db.close()


app = FastAPI(
    title="Bedrock Model Monitoring",
    description="Monitor latency, throughput, and reliability of AWS Bedrock LLM models.",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware - allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(probes.router)
app.include_router(results.router)
app.include_router(prompts.router)
app.include_router(models.router)
app.include_router(auto_probe.router)
app.include_router(auth_router.router)
app.include_router(chat_router.router)
app.include_router(insights_router.router)
app.include_router(admin_router.router)
app.include_router(compare_router.router)
app.include_router(cost_router.router)
app.include_router(reliability_router.router)
app.include_router(efficiency_router.router)
app.include_router(analysis_router.router)


@app.get("/api/health", tags=["health"])
def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}
