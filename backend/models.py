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
    prompt_category = Column(Text, nullable=True)  # e.g. explanation, summary, reasoning, coding, korean, math

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
