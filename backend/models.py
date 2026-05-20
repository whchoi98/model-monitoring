from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Integer,
    Text,
    Float,
    DateTime,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import relationship

from database import Base


class ProbeRun(Base):
    __tablename__ = "probe_runs"

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
