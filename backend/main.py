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
from routers import auth as auth_router
from routers import chat as chat_router
from routers import insights as insights_router

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

    # Migrations
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE probe_runs ADD COLUMN IF NOT EXISTS is_auto INTEGER DEFAULT 0"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS approved INTEGER DEFAULT 0"))
        conn.commit()

    # Seed default admin user if no users exist
    _seed_default_admin()
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

    if len(seed_password) < 12:
        logger.warning(
            "SEED_ADMIN_PASSWORD 미설정 또는 12자 미만 - admin 시드 skip. "
            "운영자가 별도 절차로 첫 사용자를 생성해야 합니다."
        )
        return

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            admin = User(
                username=seed_username,
                password_hash=hash_password(seed_password),
                approved=1,
            )
            db.add(admin)
            db.commit()
            logger.info("Default admin user '%s' created from env vars.", seed_username)
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


@app.get("/api/health", tags=["health"])
def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}
