"""FastAPI application entry point for the Bedrock LLM Model Monitoring Tool."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect as sa_inspect
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
from routers import parity as parity_router
from routers import gptbench as gptbench_router
from routers import features as features_router
from routers import pricing as pricing_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 단가 열 마이그레이션과 seed의 백그라운드 재시도 (v2.31.0, _retry_price_schema) — 테스트가 줄일 수 있게 모듈 상수로 둔다.
PRICE_SCHEMA_RETRY_ATTEMPTS = 3
PRICE_SCHEMA_RETRY_INTERVAL_S = 30.0

# lifespan 마이그레이션 블록이 확인하는 열 (테이블, 열, ADD COLUMN 타입). 운영 DB에는 v2 초기부터 모두 있다.
_STARTUP_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("probe_runs", "is_auto", "INTEGER DEFAULT 0"),
    ("users", "approved", "INTEGER DEFAULT 0"),
    ("insights", "summary_md_en", "TEXT"),
    ("probe_results", "category", "TEXT"),     # Phase 3 Workload Preset
    ("probe_results", "stop_reason", "TEXT"),  # Output Analysis (stop_reason 분포 + output 길이 통계)
)


def _add_missing_startup_columns(conn) -> list[str]:
    """_STARTUP_COLUMNS 중 빠진 열만 더하고, 더한 열을 "테이블.열"로 _STARTUP_COLUMNS 순서대로 돌려준다 (v2.32.2).

    ALTER TABLE … ADD COLUMN IF NOT EXISTS는 PostgreSQL에서 열이 있는지 보기 전에 ACCESS EXCLUSIVE 락부터 요청한다. 그래서 열이
    이미 있어도 그 테이블을 읽는 트랜잭션 하나에 lock_timeout까지 막히고, 기다리는 동안 뒤에 온 평범한 읽기까지 줄을 세운다
    (2026-09-30 운영 기동 4번 중 2번, Insights 태스크가 probe_runs, probe_results를 쥔 동안 5초 뒤 LockNotAvailable). 여기서는
    카탈로그(sqlalchemy inspect, 테이블마다 한 번)로 먼저 확인해 있는 열에는 DDL을 내지 않는다. 호출부 트랜잭션에서 advisory 락
    (pg_advisory_xact_lock) 다음에 읽는다. 앞선 기동의 트랜잭션 락은 그 커밋이 보이게 된 뒤에 풀리고 카탈로그 조회는 락을 잡은 뒤의
    새 문장(READ COMMITTED)이라, 앞선 기동이 더한 열은 보인다(세션 락을 finally에서 풀면 unlock이 커밋보다 먼저라, 그 틈에 겹친
    기동은 아직 안 보이는 열에 ALTER를 낸다). 빠진 열은 PostgreSQL에서 v2.32.1과 같은 문장(IF NOT EXISTS 포함)으로 더하고, 그
    ALTER는 예전처럼 lock_timeout까지 기다릴 수 있다. 그 밖의 방언(SQLite 테스트)은 IF NOT EXISTS 없이 더한다.
    """
    inspector = sa_inspect(conn)
    if_not_exists = " IF NOT EXISTS" if conn.dialect.name == "postgresql" else ""
    present: dict[str, set[str]] = {}
    added: list[str] = []
    for table, column, ddl in _STARTUP_COLUMNS:
        if table not in present:
            present[table] = {col["name"] for col in inspector.get_columns(table)}
        if column in present[table]:
            continue
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN{if_not_exists} {column} {ddl}"))
        present[table].add(column)
        added.append(f"{table}.{column}")
    return added


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
    # advisory lock(917350001)으로 한 번에 한 task만 마이그레이션 실행하도록 serialize.
    # 마이그레이션은 try/except로 감싸 backend startup이 절대 hang되지 않도록 보호.
    # statement_timeout으로 개별 쿼리 최대 30초 제한.
    # 실패해도 backend는 시작 — 마이그레이션은 다음 배포 또는 수동으로 retry.
    # 설정 두 개와 advisory 락은 이 트랜잭션 한정이다(SET LOCAL, pg_advisory_xact_lock — v2.32.2). 블록이 쓴 커넥션은 풀로
    # 돌아간다. v2.32.1의 세션 수준 SET은 그 커넥션의 이후 요청을 5초 lock_timeout, 30초 statement_timeout으로 돌게 했고,
    # 세션 락(pg_advisory_lock)은 블록이 실패하면 finally의 unlock이 중단된 트랜잭션에서 실패해 그 커넥션에 남아, 커넥션이
    # 재활용될 때까지 다음 태스크의 기동을 lock_timeout 뒤 실패시켰다. 트랜잭션 락은 커밋이나 롤백에 풀리므로 unlock이 없다.
    try:
        with engine.begin() as conn:  # begin은 commit/rollback 자동 + 연결 항상 반환
            conn.execute(text("SET LOCAL statement_timeout = '30000'"))
            # lock_timeout: ALTER TABLE … ADD COLUMN IF NOT EXISTS는 no-op이어도 ACCESS EXCLUSIVE 락을
            # 요청한다. 다른 세션이 락을 쥐고 있으면 이 요청이 대기열에 서고, 그 뒤의 모든 읽기까지
            # 함께 막힌다(2026-09-06 배포 창마다 /api/insights/latest 30s 타임아웃 연쇄). 5초 안에
            # 못 잡으면 블록을 포기하고 기동을 계속한다 — 마이그레이션은 다음 기동에 재시도.
            # v2.32.2부터 있는 열에는 ALTER를 내지 않으므로(_add_missing_startup_columns) 이 대기는 열이 정말 빠진 기동에만 생긴다.
            # advisory 락을 기다리는 것도 이 5초가 상한이다(겹친 기동은 5초 뒤 블록을 포기한다).
            conn.execute(text("SET LOCAL lock_timeout = '5000'"))
            conn.execute(text("SELECT pg_advisory_xact_lock(917350001)"))
            # 열 5개는 카탈로그로 먼저 확인하고 빠진 열만 더한다 (2026-09-30 Insights 읽기 트랜잭션 아래 LockNotAvailable).
            # 아래 DELETE, UPDATE의 테이블 락은 ROW EXCLUSIVE라 다른 트랜잭션의 읽기, 쓰기와 충돌하지 않는다.
            added_columns = _add_missing_startup_columns(conn)
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
            # engine.begin()이 자동 commit(실패하면 rollback)하므로 explicit commit 불필요 — 그때 advisory 락과 SET LOCAL도 풀린다
        if added_columns:  # 커밋된 뒤에만 남긴다
            logger.info("Startup columns added: %s", ", ".join(added_columns))
    except Exception:
        logger.exception("Migration block failed (non-fatal, backend continues)")

    # 성능 인덱스 (2026-07-08). 위 마이그레이션 트랜잭션(30s timeout) 밖에서 실행 —
    # 22만+ 행 테이블의 CREATE INDEX가 30초를 초과해 실패한 실사고(2026-07-09) 재발 방지.
    # PG에서는 CONCURRENTLY + 10분 timeout (쓰기 블로킹 없음). 상세는 models.py 참고.
    # 최상단 `from routers import models`와 이름 충돌하므로 지점 import.
    # 2026-09-06부터 백그라운드 스레드: 큰 테이블의 CONCURRENTLY 빌드가 수 분 걸려도 /api/health가
    # 먼저 열려야 ALB 헬스체크 유예(300s) 안에 기동한다. 이 기동의 마이그레이션은 인덱스 없이 돌고,
    # 다음 기동부터 인덱스를 쓴다.
    def _ensure_indexes_background() -> None:
        try:
            from models import ensure_performance_indexes

            ensure_performance_indexes(engine)
            logger.info("Performance indexes ensured (background).")
        except Exception:
            logger.exception("Performance index creation failed (non-fatal, backend continues)")

    threading.Thread(target=_ensure_indexes_background, name="perf-indexes", daemon=True).start()

    # Seed default admin user if no users exist
    _seed_default_admin()

    # Anthropic 직접 API 모델 자동 발견 (ANTHROPIC_API_KEY 설정 시에만 동작)
    try:
        from prober import _discover_anthropic_models, _register_openai_models
        _discover_anthropic_models()
        _register_openai_models()
    except Exception:
        logger.exception("Model discovery/registration failed (non-fatal)")

    # 저장 행의 model_name을 현행 카탈로그 라벨과 일치시킴 (v2.22.1). 위 `_label_renames`는
    # 같은 트랜잭션의 ALTER TABLE statement_timeout으로 함께 롤백되는 상태라 별도 트랜잭션.
    # 카탈로그가 완성된(CP/OpenAI 등록 후) 시점에 실행해야 하므로 여기 위치 고정.
    try:
        from label_repair import repair_model_labels
        from prober import AVAILABLE_MODELS
        repair_model_labels(engine, AVAILABLE_MODELS)
    except Exception:
        logger.exception("Label repair failed (non-fatal)")

    # 단가 열(v2.31.0)과 단가 seed(v2.30.0) — CP seed가 활성 CP model_id로 풀리므로 모델 등록 다음에 둔다.
    # 실패하면 백그라운드 스레드가 다시 시도한다(기동은 기다리지 않는다).
    _ensure_price_schema()

    logger.info("Database tables ready.")

    yield


def _ensure_price_schema() -> Optional[threading.Thread]:
    """lifespan의 단가 열 마이그레이션과 단가 seed. 둘 중 하나라도 실패하면 재시도 스레드를 띄우고 그 스레드를 돌려준다.

    둘 다 성공하면 스레드 없이 None이다. 실패해도 기동은 계속하고, 여기서는 기다리지 않는다(재시도는 _retry_price_schema).
    """
    failed = False
    # 단가 표시 전용 열 7개 (v2.31.0) — 운영 price_history는 이미 있어 create_all이 새 열을 더하지 않는다.
    # 빠진 열이 없으면 DDL 없이 끝난다(ADD COLUMN은 no-op이어도 ACCESS EXCLUSIVE 락을 요청). 아래 seed가 새 열에 값을
    # 넣으므로 seed 블록 바로 앞에 둔다. 실패해도 기동은 계속한다 — 아래 재시도 스레드가 다시 한다.
    try:
        from pricing_seed import ensure_price_columns
        ensure_price_columns(engine)
    except Exception:
        failed = True
        logger.exception("Price column migration failed (non-fatal, backend continues)")

    # 단가 seed (v2.30.0, ADR-030) — price_history에 행이 하나도 없는 활성 model_id에만 공식 단가 seed를 넣는다.
    # CP seed는 family_key 단위라 현재 활성 CP model_id로 풀어 넣어야 하므로 모델 등록 다음에 둔다.
    # 마이그레이션과 분리된 자체 트랜잭션 + pg_advisory_xact_lock(917350003) — 실패해도 기동은 계속한다.
    active = None
    try:
        from pricing_seed import ensure_seed
        from pricing_sources import active_channels
        from prober import AVAILABLE_MODELS
        from visibility import hidden_patterns
        active = active_channels(AVAILABLE_MODELS, hidden_patterns())
        ensure_seed(engine, active)
    except Exception:
        failed = True
        logger.exception("Price seed failed (non-fatal, backend continues)")

    # 활성 채널 집합조차 만들지 못했으면(import나 코드 오류) 다시 해도 같으므로 스레드를 띄우지 않는다.
    if not failed or active is None:
        return None
    thread = threading.Thread(target=_retry_price_schema, args=(active,), name="price-schema-retry", daemon=True)
    thread.start()
    return thread


def _retry_price_schema(active) -> bool:
    """기동 때 실패한 단가 열 마이그레이션과 seed를 백그라운드에서 다시 시도한다 (v2.31.0).

    ALTER TABLE은 ACCESS EXCLUSIVE 잠금이 필요해 price_history를 읽거나 쓰는 트랜잭션(롤링 배포 중 다른 backend 태스크의
    /api/cost/*, /api/efficiency/score, /api/pricing 조회, 실행 중인 PricingSync)과 겹치면 lock_timeout 5초에 걸려 실패한다.
    그대로 두면 새 열이 없어 /api/pricing이 다음 재기동이나 PricingSync까지 500이다. PRICE_SCHEMA_RETRY_INTERVAL_S초 간격으로
    최대 PRICE_SCHEMA_RETRY_ATTEMPTS번 ensure_price_columns → ensure_seed(기동 때와 같은 활성 채널 집합)를 다시 하고, 처음
    성공하면 멈춘다. 두 함수 모두 멱등이라 이미 끝난 단계는 no-op이다. 성공하면 True, 모두 실패하면 False.
    """
    for attempt in range(1, PRICE_SCHEMA_RETRY_ATTEMPTS + 1):
        time.sleep(PRICE_SCHEMA_RETRY_INTERVAL_S)
        try:
            from pricing_seed import ensure_price_columns, ensure_seed
            ensure_price_columns(engine)
            ensure_seed(engine, active)
        except Exception:
            logger.exception("Price schema retry %d/%d failed", attempt, PRICE_SCHEMA_RETRY_ATTEMPTS)
            continue
        logger.info("Price schema retry %d/%d succeeded", attempt, PRICE_SCHEMA_RETRY_ATTEMPTS)
        return True
    logger.error("Price schema retries exhausted (%d); run PricingSync once or restart the backend",
                 PRICE_SCHEMA_RETRY_ATTEMPTS)
    return False


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
    # OpenAPI(/docs)에 노출되는 런타임 버전 — 릴리스 시 CLAUDE.md "Version strings" 목록과 함께 범프.
    version="2.32.1",
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
app.include_router(parity_router.router)
app.include_router(gptbench_router.router)
app.include_router(features_router.router)
app.include_router(pricing_router.router)
app.include_router(pricing_router.admin_router)


@app.get("/api/health", tags=["health"])
def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}
