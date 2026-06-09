"""Auto-prober — Phase 8부터 데몬 스레드 제거.

v1: backend 프로세스 내부 데몬 스레드가 5분마다 자동 호출.
v2: EventBridge Scheduler가 별도 Fargate Task(`auto_prober_runner`)를 5분마다 실행.

본 모듈은 두 가지 경로에서 재사용되는 `_run_cycle()`만 노출:
  - Fargate one-shot runner (`backend.auto_prober_runner`)
  - 수동 trigger API (`/api/auto-probe/trigger`) — backend 프로세스에서 동기 실행
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from queue import Queue
from typing import Optional

from database import SessionLocal
from models import ProbeRun
from prober import AVAILABLE_MODELS, _get_bedrock_client, _get_region_for_model, _probe_single_model

logger = logging.getLogger(__name__)

# Phase 3 Workload Preset — round-robin 카테고리.
# 각 cycle마다 다음 카테고리로 회전 → use case별 latency/cost 분포가 시계열로 누적.
# max_tokens는 각 카테고리에 맞춰 (짧은 chat은 작게, 추론은 크게) — 비용/지연 차이 명확화.
WORKLOAD_PRESETS: list[dict] = [
    {
        "id": "chat-short",
        "label_ko": "짧은 대화",
        "label_en": "Short chat",
        "prompt": "What is cloud computing? Answer in one sentence.",
        "max_tokens": 80,
    },
    {
        "id": "reasoning",
        "label_ko": "추론",
        "label_en": "Reasoning",
        "prompt": (
            "Solve step by step. Alice arrives at 9 AM every weekday. "
            "Bob works from home on Tuesdays and Thursdays (works exactly 7.5 hours); "
            "on other weekdays he arrives at 8:30 AM. Both take 1 hour for lunch. "
            "Alice leaves at 6 PM; Bob leaves at 5:30 PM on office days. "
            "In a month with 22 weekdays, what is the difference in total work hours between Alice and Bob?"
        ),
        "max_tokens": 512,
    },
    {
        "id": "code-gen",
        "label_ko": "코드 생성",
        "label_en": "Code generation",
        "prompt": (
            "Write a minimal Python function `parse_iso8601(s: str) -> datetime` that parses an ISO-8601 "
            "timestamp string with optional timezone offset and returns a tzaware datetime. "
            "Include a docstring and one usage example."
        ),
        "max_tokens": 400,
    },
    {
        "id": "summarize",
        "label_ko": "요약",
        "label_en": "Summarization",
        "prompt": (
            "Summarize the text below in 2 sentences. "
            "Text: Amazon Bedrock is a fully managed service that offers foundation models from Anthropic, "
            "Cohere, AI21 Labs, Meta, Mistral AI, Stability AI, and Amazon Titan/Nova through a single API. "
            "Developers build enterprise-grade GenAI applications without managing model hosting infrastructure, "
            "leveraging RAG, agents, fine-tuning, guardrails, and model evaluation. "
            "Cross-region inference profiles increase availability and KMS+VPC endpoints meet security needs."
        ),
        "max_tokens": 200,
    },
    {
        "id": "structured",
        "label_ko": "JSON 추출",
        "label_en": "JSON extraction",
        "prompt": (
            "Extract company, title, email, and phone as JSON only (null if missing). "
            "Text: Hi, I'm Charles Kim, Senior Cloud Architect at ACME Corporation. "
            "Reach me at kim.cs@acme-corp.com or +1-555-1234."
        ),
        "max_tokens": 200,
    },
    {
        "id": "translate",
        "label_ko": "번역",
        "label_en": "Translation",
        "prompt": (
            "Translate to natural Korean preserving technical nuance: "
            "Server-Sent Events (SSE) is a unidirectional protocol that allows a server to push real-time "
            "updates to a client over a single long-lived HTTP connection. Unlike WebSockets, SSE only flows "
            "from server to client and uses standard HTTP, making it simpler to proxy, cache, and secure."
        ),
        "max_tokens": 400,
    },
]


def _next_preset() -> dict:
    """직전 ProbeRun의 카테고리 다음 preset을 round-robin으로 반환.

    DB에서 가장 최근 auto run의 prompt(또는 첫 result의 category)를 봐서 다음 index 결정.
    실패하면 첫 preset.
    """
    try:
        db = SessionLocal()
        try:
            from models import ProbeResult
            # 직전 auto run의 첫 row의 category 조회
            row = (
                db.query(ProbeResult.category)
                .join(ProbeRun, ProbeRun.id == ProbeResult.run_id)
                .filter(ProbeRun.is_auto == 1)
                .order_by(ProbeResult.id.desc())
                .first()
            )
            last_id = row[0] if row else None
            if last_id is None:
                return WORKLOAD_PRESETS[0]
            for i, p in enumerate(WORKLOAD_PRESETS):
                if p["id"] == last_id:
                    return WORKLOAD_PRESETS[(i + 1) % len(WORKLOAD_PRESETS)]
            return WORKLOAD_PRESETS[0]
        finally:
            db.close()
    except Exception:
        logger.exception("_next_preset failed - fallback to first preset")
        return WORKLOAD_PRESETS[0]


# Legacy fallback (in-process trigger 호환). v2에서는 _next_preset이 우선.
PROBE_PROMPT = WORKLOAD_PRESETS[0]["prompt"]


class AutoProber:
    """단순 컨테이너 — in-process status 추적 (트리거 endpoint 가독성용)."""

    def __init__(self) -> None:
        self.last_run_time: Optional[datetime] = None
        self.current_cycle_running = False
        # v1 호환 필드 — v2에서는 외부 Scheduler가 관리하므로 항상 False.
        self.is_running = False
        self.next_run_time: Optional[datetime] = None

    def trigger(self) -> None:
        """수동 트리거 — backend 프로세스 별도 스레드에서 1회 실행."""
        threading.Thread(target=self._run_once_safe, daemon=True).start()

    def _run_once_safe(self) -> None:
        try:
            run_cycle()
        except Exception:
            logger.exception("auto_prober manual trigger 실행 실패")


def run_cycle() -> int:
    """모든 모델을 한 번 프로빙하고 DB에 결과를 저장. run_id 반환.

    Phase 3: workload preset round-robin — 매 cycle마다 다음 카테고리 prompt 사용.
    """
    auto_prober.current_cycle_running = True
    preset = _next_preset()
    cur_prompt = preset["prompt"]
    cur_max_tokens = preset["max_tokens"]
    cur_category = preset["id"]
    logger.info("AutoProber: starting probe cycle (preset=%s, max_tokens=%d)", cur_category, cur_max_tokens)

    db = SessionLocal()
    try:
        run = ProbeRun(
            prompt=cur_prompt,
            temperature=0.1,
            max_tokens=cur_max_tokens,
            concurrency=3,
            repeat_count=1,
            status="running",
            is_auto=1,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    except Exception:
        logger.exception("AutoProber: failed to create probe run")
        db.close()
        auto_prober.current_cycle_running = False
        raise

    event_queue: Queue = Queue()

    # 각 probe는 자신의 DB 세션을 worker 안에서 생성하고 finally에서 즉시 닫는다.
    # 과거 버그(2026-06-09): 모델당 SessionLocal()을 submit 루프에서 미리 만들고 in-order
    # 결과 루프에서야 close → 느린 probe 하나(예: Opus 4.8 Global read-timeout)가 루프를
    # 막으면 완료된 세션들의 connection이 쌓여 pool(5+5=10)을 고갈시킴(commit 후 db.refresh가
    # read 트랜잭션을 close까지 유지). 모델 수 12→15 확장으로 한계를 넘어 tail 모델들이
    # "QueuePool limit reached"로 persist 실패. 세션 수명을 worker 실행에 묶어 동시
    # connection 수를 max_workers로 제한 → 모델 수와 무관하게 안전.
    def _probe_worker(client, model_id: str, model_name: str) -> None:
        thread_db = SessionLocal()
        try:
            _probe_single_model(
                client,
                model_id,
                model_name,
                cur_prompt,
                0.1,
                cur_max_tokens,
                1,
                event_queue,
                run_id,
                thread_db,
                cur_category,  # category 전달
            )
        finally:
            thread_db.close()

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        for model_id, model_name in AVAILABLE_MODELS.items():
            client = _get_bedrock_client(_get_region_for_model(model_id))
            futures.append(executor.submit(_probe_worker, client, model_id, model_name))

        for future in futures:
            try:
                future.result(timeout=120)
            except Exception:
                logger.exception("AutoProber: model probe failed")

    try:
        run = db.query(ProbeRun).filter(ProbeRun.id == run_id).first()
        if run:
            run.status = "completed"
            db.commit()
    except Exception:
        logger.exception("AutoProber: failed to update run status")
    finally:
        db.close()

    auto_prober.last_run_time = datetime.now(timezone.utc)
    auto_prober.current_cycle_running = False
    logger.info("AutoProber: cycle completed (run_id=%d)", run_id)
    return run_id


# 싱글톤 — 트리거 endpoint가 in-process status를 읽는 용도.
auto_prober = AutoProber()
