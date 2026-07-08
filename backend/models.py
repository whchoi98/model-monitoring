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


def ensure_performance_indexes(conn) -> None:
    """기존 DB에 성능 인덱스를 멱등하게 생성 (main.py lifespan 마이그레이션에서 호출).

    신규 DB는 create_tables()가 모델 선언 인덱스를 함께 만들지만, 이미 테이블이
    존재하는 운영 DB에는 create_all이 인덱스를 추가하지 않으므로 이 헬퍼가 필요하다.
    IF NOT EXISTS라 반복 실행에 안전. (일반 CREATE INDEX는 쓰기 잠깐 블록 — 수 초 수준.)
    """
    for idx in (*ProbeRun.__table__.indexes, *ProbeResult.__table__.indexes):
        conn.execute(CreateIndex(idx, if_not_exists=True))
