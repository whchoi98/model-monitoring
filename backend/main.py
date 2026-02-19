"""FastAPI application entry point for the Bedrock LLM Model Monitoring Tool."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from auto_prober import auto_prober
from database import create_tables, engine, SessionLocal
from routers import models, probes, prompts, results
from routers import auto_probe
from routers import auth as auth_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: run startup tasks before yielding, cleanup after."""
    logger.info("Creating database tables...")
    create_tables()

    # Migrations
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE probe_runs ADD COLUMN IF NOT EXISTS is_auto INTEGER DEFAULT 0"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS approved INTEGER DEFAULT 0"))
        conn.execute(text("ALTER TABLE probe_runs ADD COLUMN IF NOT EXISTS prompt_category TEXT"))
        conn.commit()

    # Seed default admin user if no users exist
    _seed_default_admin()
    logger.info("Database tables ready.")

    auto_prober.start()
    yield
    auto_prober.stop()


def _seed_default_admin():
    """Create a default admin user if the users table is empty."""
    from auth import hash_password
    from models import User

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            default_password = os.environ.get("DEFAULT_ADMIN_PASSWORD", "changeme")
            admin = User(username="admin", password_hash=hash_password(default_password), approved=1)
            db.add(admin)
            db.commit()
            logger.info("Default admin user created (username: admin)")
    except Exception:
        logger.exception("Failed to seed default admin user")
    finally:
        db.close()


app = FastAPI(
    title="Bedrock Model Monitoring",
    description="Monitor latency, throughput, and reliability of AWS Bedrock LLM models.",
    version="1.0.0",
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


@app.get("/api/health", tags=["health"])
def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}
