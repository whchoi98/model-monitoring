from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ModelInfo(BaseModel):
    id: str
    name: str


# ---------------------------------------------------------------------------
# Probe requests / responses
# ---------------------------------------------------------------------------

class ProbeRunRequest(BaseModel):
    model_ids: list[str]
    prompt: str
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    max_tokens: int = Field(default=256, ge=1, le=4096)
    concurrency: int = Field(default=1, ge=1, le=20)
    repeat_count: int = Field(default=1, ge=1, le=50)


class ProbeResultResponse(BaseModel):
    id: int
    run_id: int
    model_id: str
    model_name: str
    timestamp: datetime
    prompt: str
    status: str
    ttft_ms: Optional[float] = None
    total_latency_ms: Optional[float] = None
    server_latency_ms: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    tps: Optional[float] = None
    output_text: Optional[str] = None
    error_message: Optional[str] = None
    iteration: int = 1
    prompt_category: Optional[str] = None

    model_config = {"from_attributes": True}


class ProbeRunResponse(BaseModel):
    id: int
    created_at: datetime
    prompt: str
    temperature: float
    max_tokens: int
    concurrency: int
    repeat_count: int
    status: str
    is_auto: int = 0
    prompt_category: Optional[str] = None
    results: list[ProbeResultResponse] = []

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class ModelStats(BaseModel):
    model_id: str
    model_name: str
    count: int
    avg_ttft_ms: Optional[float] = None
    p50_ttft_ms: Optional[float] = None
    p95_ttft_ms: Optional[float] = None
    p99_ttft_ms: Optional[float] = None
    avg_latency_ms: Optional[float] = None
    p50_latency_ms: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    p99_latency_ms: Optional[float] = None
    avg_tps: Optional[float] = None
    p50_tps: Optional[float] = None
    p95_tps: Optional[float] = None
    p99_tps: Optional[float] = None
    avg_server_latency_ms: Optional[float] = None
    p50_server_latency_ms: Optional[float] = None
    p95_server_latency_ms: Optional[float] = None
    p99_server_latency_ms: Optional[float] = None


class StatsResponse(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    models: list[ModelStats] = []


# ---------------------------------------------------------------------------
# Prompt sets
# ---------------------------------------------------------------------------

class PromptSetCreate(BaseModel):
    name: str
    prompts: list[str]
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    max_tokens: int = Field(default=256, ge=1, le=4096)


class PromptSetResponse(BaseModel):
    id: int
    name: str
    prompts: list[str]
    temperature: float
    max_tokens: int
    created_at: datetime

    model_config = {"from_attributes": True}
