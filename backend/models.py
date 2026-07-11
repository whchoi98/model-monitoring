from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Index,
    Integer,
    Text,
    Float,
    DateTime,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.schema import CreateIndex

from database import Base


class ProbeRun(Base):
    __tablename__ = "probe_runs"
    # trend/status/latest 공통 조건: WHERE is_auto=1 AND status='completed' + created_at 범위/정렬.
    # 등호 컬럼 앞, 범위/정렬 컬럼 뒤 순서.
    __table_args__ = (
        Index("ix_probe_runs_auto_status_created", "is_auto", "status", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    prompt = Column(Text, nullable=False)
    temperature = Column(Float, default=0.1)
    max_tokens = Column(Integer, default=256)
    concurrency = Column(Integer, default=1)
    repeat_count = Column(Integer, default=1)
    status = Column(Text, default="running")  # running | completed | failed
    is_auto = Column(Integer, default=0)  # 0=manual, 1=auto

    results = relationship("ProbeResult", back_populates="run", lazy="selectin")


class ProbeResult(Base):
    __tablename__ = "probe_results"
    # run_id: trend/latest의 JOIN·IN 조회. timestamp: cost/reliability/efficiency/analysis의 범위 필터.
    __table_args__ = (
        Index("ix_probe_results_run_id", "run_id"),
        Index("ix_probe_results_timestamp", "timestamp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("probe_runs.id"), nullable=False)
    model_id = Column(Text, nullable=False)
    model_name = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    prompt = Column(Text, nullable=False)
    status = Column(Text, nullable=False)  # success | error
    ttft_ms = Column(Float, nullable=True)
    total_latency_ms = Column(Float, nullable=True)
    server_latency_ms = Column(Float, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    tps = Column(Float, nullable=True)
    output_text = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    iteration = Column(Integer, default=1)
    # Phase 3 Workload Preset - auto-prober가 회전한 카테고리 식별자 (예: "chat-short", "reasoning").
    # nullable로 두어 기존 row 호환. 신규 row는 항상 채움.
    category = Column(Text, nullable=True)
    # Output Analysis - Bedrock messageStop.stopReason 또는 Anthropic final_message.stop_reason.
    # 값: end_turn | max_tokens | stop_sequence | tool_use | guardrail_intervened | content_filtered | null
    stop_reason = Column(Text, nullable=True)

    run = relationship("ProbeRun", back_populates="results")


class ProbeResultHourly(Base):
    """보존 기간(RETENTION_DAYS, 기본 60일)을 지난 probe_results의 시간 단위 집계 보관.

    retention.apply_retention()이 원본 삭제 전에 (model, category, 정시 버킷)별로 집계해
    이관한다. 장기 히스토리(비용 추정용 토큰 합계 포함)를 손실 없이 보존하면서
    원본 테이블 크기를 상수 수준으로 유지하는 것이 목적.
    """

    __tablename__ = "probe_results_hourly"
    __table_args__ = (
        Index("ix_probe_results_hourly_bucket_ts", "bucket_ts"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    bucket_ts = Column(DateTime(timezone=True), nullable=False)  # 정시(hour) 버킷 시작
    model_id = Column(Text, nullable=False)
    model_name = Column(Text, nullable=False)
    category = Column(Text, nullable=True)
    cnt = Column(Integer, nullable=False)          # 버킷 내 전체 probe 수
    success_cnt = Column(Integer, nullable=False)  # status == "success" 수
    avg_ttft_ms = Column(Float, nullable=True)     # null metric 제외 평균
    avg_total_latency_ms = Column(Float, nullable=True)
    avg_tps = Column(Float, nullable=True)
    sum_input_tokens = Column(Integer, nullable=True)   # 비용 재계산용
    sum_output_tokens = Column(Integer, nullable=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(Text, nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    approved = Column(Integer, default=0)  # 0=pending, 1=approved
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PromptSet(Base):
    __tablename__ = "prompt_sets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False, unique=True)
    prompts = Column(JSON, nullable=False)
    temperature = Column(Float, default=0.1)
    max_tokens = Column(Integer, default=256)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Insight(Base):
    """주기 잡(insights_runner)이 생성한 모니터링 인사이트 (Sonnet 4.6 요약).

    한 row가 하나의 시간 윈도우에 대한 자연어 요약을 보관한다.
    """

    __tablename__ = "insights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    summary_md = Column(Text, nullable=False)  # 한국어 마크다운 요약 (default)
    summary_md_en = Column(Text, nullable=True)  # 영문 마크다운 요약 (i18n 'en' 모드)
    model_breakdown = Column(JSON, nullable=True)  # 모델별 stats 스냅샷
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


_PERF_INDEXES = (*ProbeRun.__table__.indexes, *ProbeResult.__table__.indexes)


class ParityRun(Base):
    """패리티 런 1회 실행 기록 (v2.11.0)."""

    __tablename__ = "parity_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, default="running")  # running | completed | failed
    totals = Column(JSON, nullable=True)  # {supported, unsupported, broken, skipped}


class ParityResult(Base):
    """패리티 프로브 1건의 판정 + 실행 증거 (v2.11.0)."""

    __tablename__ = "parity_results"
    __table_args__ = (
        Index("ix_parity_results_run_id", "run_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("parity_runs.id"), nullable=False)
    model_id = Column(Text, nullable=False)
    model_name = Column(Text, nullable=False)
    surface = Column(Text, nullable=False)   # converse | invoke_model | messages | chat_completions | responses
    feature = Column(Text, nullable=False)   # catalog.FEATURE_IDS
    status = Column(Text, nullable=False)    # supported | unsupported | broken | skipped
    latency_ms = Column(Float, nullable=True)
    evidence = Column(JSON, nullable=True)   # 요청 요약·응답 스니펫·검사 결과
    error_message = Column(Text, nullable=True)


def ensure_performance_indexes(engine) -> None:
    """기존 DB에 성능 인덱스를 멱등하게 생성 (main.py lifespan에서 호출).

    신규 DB는 create_tables()가 모델 선언 인덱스를 함께 만들지만, 이미 테이블이
    존재하는 운영 DB에는 create_all이 인덱스를 추가하지 않으므로 이 헬퍼가 필요하다.

    PG 경로 (2026-07-09 실사고 교훈): probe_results 22만 행에서 일반 CREATE INDEX가
    마이그레이션 트랜잭션의 statement_timeout(30s)을 초과해 실패했다. 그래서
    (1) 자체 AUTOCOMMIT 커넥션 (CONCURRENTLY는 트랜잭션 안에서 실행 불가),
    (2) statement_timeout 10분,
    (3) CREATE INDEX CONCURRENTLY — 쓰기(autoprober cycle) 블로킹 없음,
    (4) 이전 CONCURRENTLY 실패가 남긴 INVALID 인덱스는 드롭 후 재생성.
    """
    from sqlalchemy import text  # 지역 import — models는 기본적으로 DDL-only 모듈

    if engine.dialect.name == "postgresql":
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("SET statement_timeout = '600000'"))
            for idx in _PERF_INDEXES:
                invalid = conn.execute(
                    text(
                        "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                        "WHERE c.relname = :name AND NOT i.indisvalid"
                    ),
                    {"name": idx.name},
                ).first()
                if invalid:
                    conn.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {idx.name}"))
                cols = ", ".join(c.name for c in idx.columns)
                conn.execute(
                    text(
                        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx.name} "
                        f"ON {idx.table.name} ({cols})"
                    )
                )
    else:
        # sqlite (로컬/테스트): CONCURRENTLY 미지원 — 일반 IF NOT EXISTS로 충분.
        with engine.begin() as conn:
            for idx in _PERF_INDEXES:
                conn.execute(CreateIndex(idx, if_not_exists=True))
