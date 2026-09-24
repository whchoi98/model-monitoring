"""Auto-prober — Phase 8부터 데몬 스레드 제거.

v1: backend 프로세스 내부 데몬 스레드가 5분마다 자동 호출.
v2: EventBridge Scheduler가 별도 Fargate Task(`auto_prober_runner`)를 5분마다 실행.

본 모듈은 두 가지 경로에서 재사용되는 `_run_cycle()`만 노출:
  - Fargate one-shot runner (`backend.auto_prober_runner`)
  - 수동 trigger API (`/api/auto-probe/trigger`) — backend 프로세스에서 동기 실행

v2.29.0: 채널별 주기. Claude Platform on AWS 채널(anthropic:*)은 10분(ANTHROPIC_CP_PROBE_INTERVAL_S)
마다만 프로빙하고 워크로드 카테고리도 채널별로 따로 회전한다(_plan_cycle). 나머지 모델은 매 사이클.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from queue import Queue
from threading import Lock
from typing import Optional

from sqlalchemy import text

import probe_cadence
from database import SessionLocal
from models import ProbeResult, ProbeRun
from probe_cadence import BASE_INTERVAL_SECONDS, CP_MODEL_PREFIX, is_cp_model
from prober import (
    AVAILABLE_MODELS,
    PROBE_WALL_CLOCK_S,
    _get_bedrock_client,
    _get_region_for_model,
    _probe_single_model,
)

logger = logging.getLogger(__name__)

PROBE_INTERVAL_SECONDS = BASE_INTERVAL_SECONDS
OVERDUE_AFTER_SECONDS = PROBE_INTERVAL_SECONDS * 2
RUNNING_TIMEOUT_SECONDS = PROBE_INTERVAL_SECONDS * 3
# Serialize only admission, never paid work. PostgreSQL covers separate API /
# scheduled processes; the local lock also supports SQLite and same-process races.
_CYCLE_ADMISSION_LOCK_KEY = 917350002
_admission_lock = threading.Lock()

# 모델 1개의 사이클 상한 (v2.28.2) — 워커가 실제로 시작한 시점부터 잰다. prober의 wall-clock
# 상한(PROBE_WALL_CLOCK_S, 기본 90s)보다 여유(30s) 있게 커야 watchdog이 먼저 원인이 분명한 오류 행
# (WallClockTimeout)을 남긴다. 이 값은 watchdog이 끊을 수 없는 구간(응답 헤더 대기, DB 커밋 등)까지
# 포함한 최종 안전망이다 — 넘기면 사이클이 그 모델만 오류 행으로 기록하고 run은 정상 완료한다.
PROBE_FUTURE_TIMEOUT_S = max(120.0, PROBE_WALL_CLOCK_S + 30.0)
# 사이클 전체 상한 — 포기한 워커 스레드가 풀(3)을 채워 대기 중인 모델이 시작조차 못하는 경우의
# 안전망. RUNNING_TIMEOUT_SECONDS(900s)보다 충분히 작아야 예약이 만료되기 전에 run이 끝난다.
CYCLE_DEADLINE_SECONDS = float(RUNNING_TIMEOUT_SECONDS - PROBE_INTERVAL_SECONDS)  # 600s
_CYCLE_POLL_SECONDS = 1.0

# Claude Platform on AWS 채널 주기 판정 (v2.29.0) — 직전 CP 자동 프로브가 속한 run의 시작 시각
# (ProbeRun.created_at, 사이클 예약 시각)과 이번 run의 시작 시각을 비교한다. 결과 행 timestamp는 기준으로
# 쓰지 않는다: CP 행은 사이클 안에서 Bedrock 모델 뒤에 쓰여 시작 후 1~2분 늦게 찍히므로(2026-09-23 로그),
# 행 기준이면 두 사이클 뒤에도 "10분 미만"으로 보여 15분 주기가 된다. 허용 오차는 사이클의 절반(150s) —
# Fargate 기동 지연 때문에 스케줄 run 간격이 281~312s로 흔들려(같은 로그) 두 사이클 간격이 540s 아래로
# 내려갈 수 있다. 한 사이클 뒤(≈300s)는 여전히 오차 밖이라 걸러진다.
CP_DUE_TOLERANCE_SECONDS = PROBE_INTERVAL_SECONDS // 2
# 직전 CP 행 조회 범위(ix_probe_results_timestamp range). 이보다 오래됐으면 due + 사이클 카테고리로 재시작.
_CP_HISTORY_MIN_LOOKBACK_SECONDS = 3600

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


def _preset_after(category_id: Optional[str]) -> Optional[dict]:
    """category_id 다음 preset (round-robin). 모르는 id나 None이면 None."""
    for i, p in enumerate(WORKLOAD_PRESETS):
        if p["id"] == category_id:
            return WORKLOAD_PRESETS[(i + 1) % len(WORKLOAD_PRESETS)]
    return None


def _next_preset() -> dict:
    """직전 ProbeRun의 카테고리 다음 preset을 round-robin으로 반환.

    DB에서 가장 최근 auto 결과 행(CP 채널 제외)의 category를 봐서 다음 index 결정. 실패하면 첫 preset.
    CP 채널(anthropic:*)은 v2.29.0부터 자기 회전을 따로 돌아 같은 run 안에서도 카테고리가 다를 수 있다 —
    그 행을 읽으면 나머지 모델의 회전이 흔들리므로 제외한다.
    """
    try:
        db = SessionLocal()
        try:
            row = (
                db.query(ProbeResult.category)
                .join(ProbeRun, ProbeRun.id == ProbeResult.run_id)
                .filter(ProbeRun.is_auto == 1, ~ProbeResult.model_id.startswith(CP_MODEL_PREFIX))
                .order_by(ProbeResult.id.desc())
                .first()
            )
            last_id = row[0] if row else None
            return _preset_after(last_id) or WORKLOAD_PRESETS[0]
        finally:
            db.close()
    except Exception:
        logger.exception("_next_preset failed - fallback to first preset")
        return WORKLOAD_PRESETS[0]


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite는 tz 없는 datetime을 돌려준다 — 저장 값은 UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _cp_history(run_id: int) -> tuple[datetime, dict[str, tuple[Optional[datetime], Optional[str]]]]:
    """(이번 run 시작 시각, {CP model_id: (직전 CP 자동 프로브 run의 시작 시각, 그 행의 category)}).

    run 상태와 무관하게 모든 자동 run의 행을 센다 — 실패한 run의 행도 실제 API 호출이었다.
    범위는 timestamp 인덱스로 최근 max(1h, 3 × CP 주기)만 읽는다(CP 9채널 × 6행/h).
    """
    db = SessionLocal()
    try:
        started = db.query(ProbeRun.created_at).filter(ProbeRun.id == run_id).scalar()
        now = _as_utc(started) or datetime.now(timezone.utc)
        lookback = max(_CP_HISTORY_MIN_LOOKBACK_SECONDS, 3 * probe_cadence.ANTHROPIC_CP_PROBE_INTERVAL_S)
        rows = (
            db.query(ProbeResult.model_id, ProbeResult.category, ProbeRun.created_at)
            .join(ProbeRun, ProbeRun.id == ProbeResult.run_id)
            .filter(
                ProbeRun.is_auto == 1,
                ProbeResult.run_id != run_id,
                ProbeResult.timestamp >= now - timedelta(seconds=lookback),
                ProbeResult.model_id.startswith(CP_MODEL_PREFIX),
            )
            .order_by(ProbeResult.id.desc())
            .all()
        )
        last: dict[str, tuple[Optional[datetime], Optional[str]]] = {}
        for model_id, category, run_started in rows:
            last.setdefault(model_id, (_as_utc(run_started), category))
        return now, last
    finally:
        db.close()


def _plan_cycle(run_id: int, preset: dict, models: dict[str, str]) -> list[tuple[str, str, dict]]:
    """이번 사이클에 프로빙할 (model_id, model_name, preset) 목록 (v2.29.0).

    CP 채널이 아닌 모델은 전부 사이클 preset. CP 채널은 직전 CP 자동 프로브 run이 시작된 지
    (주기 − CP_DUE_TOLERANCE_SECONDS) 이상 지났거나 최근 기록이 없을 때만 프로빙하고, 그 채널의 직전
    category 다음 preset을 쓴다(없으면 사이클 preset) — 10분 주기에서도 6개 카테고리를 모두 돈다
    (카테고리당 약 60분). 이력 조회가 실패하면 CP도 사이클 preset으로 프로빙한다(모니터링 우선).
    """
    cp_ids = [model_id for model_id in models if is_cp_model(model_id)]
    history: dict[str, tuple[Optional[datetime], Optional[str]]] = {}
    now = datetime.now(timezone.utc)
    if cp_ids:
        try:
            now, history = _cp_history(run_id)
        except Exception:
            logger.exception("AutoProber: CP cadence lookup failed - probing CP channels this cycle")
    threshold = probe_cadence.ANTHROPIC_CP_PROBE_INTERVAL_S - CP_DUE_TOLERANCE_SECONDS
    plan: list[tuple[str, str, dict]] = []
    skipped: list[str] = []
    for model_id, model_name in models.items():
        if not is_cp_model(model_id):
            plan.append((model_id, model_name, preset))
            continue
        last_started, last_category = history.get(model_id, (None, None))
        if last_started is not None and (now - last_started).total_seconds() < threshold:
            skipped.append(model_id)
            continue
        plan.append((model_id, model_name, _preset_after(last_category) or preset))
    if cp_ids:
        due = [(mid, p["id"]) for mid, _, p in plan if is_cp_model(mid)]
        logger.info(
            "AutoProber: Claude Platform on AWS %ds cadence - %d due %s, %d not due",
            probe_cadence.ANTHROPIC_CP_PROBE_INTERVAL_S, len(due),
            sorted({category for _, category in due}), len(skipped),
        )
    return plan


# Legacy fallback (in-process trigger 호환). v2에서는 _next_preset이 우선.
PROBE_PROMPT = WORKLOAD_PRESETS[0]["prompt"]


class CycleAlreadyRunning(Exception):
    def __init__(self, run_id: int):
        super().__init__("An auto-probe cycle is already running")
        self.run_id = run_id


def get_active_auto_run(db, now: datetime):
    """An old crashed runner must not look active or block admission forever."""
    return (
        db.query(ProbeRun.id, ProbeRun.created_at)
        .filter(
            ProbeRun.is_auto == 1,
            ProbeRun.status == "running",
            ProbeRun.created_at > now - timedelta(seconds=RUNNING_TIMEOUT_SECONDS),
        )
        .order_by(ProbeRun.created_at.desc(), ProbeRun.id.desc())
        .first()
    )


def _reserve_cycle() -> tuple[int, dict]:
    """Commit a run before launching work; every caller uses this admission gate."""
    with _admission_lock:
        db = SessionLocal()
        try:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": _CYCLE_ADMISSION_LOCK_KEY},
                )
            now = datetime.now(timezone.utc)
            active = get_active_auto_run(db, now)
            if active is not None:
                raise CycleAlreadyRunning(active.id)
            preset = _next_preset()
            run = ProbeRun(
                created_at=now,
                prompt=preset["prompt"],
                temperature=0.1,
                max_tokens=preset["max_tokens"],
                concurrency=3,
                repeat_count=1,
                status="running",
                is_auto=1,
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            return run.id, preset
        finally:
            db.close()


def _set_run_status(run_id: int, status: str) -> None:
    db = SessionLocal()
    try:
        run = db.query(ProbeRun).filter(ProbeRun.id == run_id).first()
        if run:
            run.status = status
            db.commit()
    finally:
        db.close()


class AutoProber:
    """단순 컨테이너 — in-process status 추적 (트리거 endpoint 가독성용)."""

    def __init__(self) -> None:
        self.last_run_time: Optional[datetime] = None
        self.current_cycle_running = False
        # v1 호환 필드 — v2에서는 외부 Scheduler가 관리하므로 항상 False.
        self.is_running = False
        self.next_run_time: Optional[datetime] = None

    def trigger(self) -> int:
        """Reserve synchronously so accepted work is immediately visible in DB."""
        run_id, preset = _reserve_cycle()
        self.current_cycle_running = True
        try:
            threading.Thread(
                target=self._run_once_safe, args=(run_id, preset),
                daemon=True, name="auto-probe",
            ).start()
        except Exception:
            self.current_cycle_running = False
            _set_run_status(run_id, "failed")
            raise
        return run_id

    def _run_once_safe(self, run_id: int, preset: dict) -> None:
        try:
            _run_reserved_cycle(run_id, preset)
        except Exception:
            logger.exception("auto_prober manual trigger 실행 실패")


def run_cycle() -> int:
    """Run one scheduled cycle, or reuse an already-active reservation.

    Phase 3: workload preset round-robin — 매 cycle마다 다음 카테고리 prompt 사용.
    """
    try:
        run_id, preset = _reserve_cycle()
    except CycleAlreadyRunning as exc:
        logger.info("AutoProber: skipping overlapping cycle (run_id=%d)", exc.run_id)
        return exc.run_id
    return _run_reserved_cycle(run_id, preset)


class _ProbeSlot:
    """모델 1개에 대해 워커 스레드와 사이클 스레드가 공유하는 상태 (v2.28.2).

    사이클이 끝나지 않는 모델을 포기(abandon)하면 그 모델의 오류 행은 사이클이 직접 쓴다. 그 뒤에
    늦게 끝난 워커의 커밋은 _SlotSession이 롤백으로 바꿔 (run_id, model_id) 행이 중복되지 않는다.
    포기와 워커 커밋은 lock 하나로 직렬화한다 — 워커 커밋이 먼저 끝났으면 사이클은 행을 쓰지 않는다.
    """

    def __init__(self, model_id: str, model_name: str, preset: Optional[dict] = None):
        self.model_id = model_id
        self.model_name = model_name
        # 이 모델의 워크로드 preset — CP 채널은 사이클 preset과 다를 수 있다 (v2.29.0).
        self.preset = preset
        self.lock = Lock()
        self.started_at: Optional[float] = None
        self.committed = False
        self.abandoned = False

    def begin(self) -> bool:
        """워커 시작. 사이클이 이미 포기한 모델이면 False (프로브하지 않는다)."""
        with self.lock:
            if self.abandoned:
                return False
            self.started_at = time.monotonic()
            return True

    def abandon(self) -> bool:
        """사이클 쪽 포기. True = 워커 행이 아직 없으니 호출자가 오류 행을 쓴다."""
        with self.lock:
            if self.committed:
                return False
            self.abandoned = True
            return True


class _SlotSession:
    """워커 DB 세션 프록시 — 사이클이 포기한 모델의 늦은 커밋을 롤백으로 바꾼다 (v2.28.2).

    _probe_single_model은 결과 행 하나를 add → commit → refresh한다. 포기된 뒤의 commit은 대기 중인
    행을 롤백으로 버리고(pending 객체는 expunge, 속성은 그대로), 이어지는 refresh는 건너뛴다.
    나머지 속성·메서드는 실제 세션으로 위임한다.
    """

    def __init__(self, session, slot: _ProbeSlot):
        self._session = session
        self._slot = slot
        self._discarded = False

    def commit(self) -> None:
        with self._slot.lock:
            if self._slot.abandoned:
                self._discarded = True
                self._session.rollback()
                logger.warning(
                    "AutoProber: discarded late result for %s (cycle already recorded a timeout row)",
                    self._slot.model_id,
                )
                return
            self._session.commit()
            self._slot.committed = True

    def refresh(self, instance, *args, **kwargs):
        if self._discarded:
            return None
        return self._session.refresh(instance, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)


def _record_unfinished_probe(run_id: int, slot: _ProbeSlot, prompt: str, category: str, reason: str) -> bool:
    """사이클이 포기한 모델의 오류 행 — _probe_single_model 오류 행과 같은 모양. 저장 실패면 False.

    prompt/category는 슬롯의 preset(모델별)이 있으면 그것을 쓴다 — CP 채널의 행은 자기 카테고리로 남는다.
    """
    if slot.preset is not None:
        prompt, category = slot.preset["prompt"], slot.preset["id"]
    started = slot.started_at
    db = SessionLocal()
    try:
        db.add(ProbeResult(
            run_id=run_id,
            model_id=slot.model_id,
            model_name=slot.model_name,
            timestamp=datetime.now(timezone.utc),
            prompt=prompt,
            status="error",
            ttft_ms=None,
            total_latency_ms=round((time.monotonic() - started) * 1000.0, 2) if started is not None else None,
            server_latency_ms=None,
            input_tokens=None,
            output_tokens=None,
            tps=None,
            output_text=None,
            error_message=reason,
            iteration=1,
            category=category,
        ))
        db.commit()
        return True
    except Exception:
        logger.exception("AutoProber: failed to record timeout row for %s", slot.model_id)
        return False
    finally:
        db.close()


def _await_probes(pending: dict[Future, _ProbeSlot], run_id: int, prompt: str, category: str) -> tuple[int, int]:
    """모든 프로브를 기다리되, 끝나지 않는 모델은 포기하고 오류 행으로 기록한다 (v2.28.2).

    반환: (failed, timed_out). failed = 워커가 예외로 끝났거나 타임아웃 행 저장 실패 — run을 failed로
    만든다(빈 completed 사이클 공개 방지, 기존 정책). timed_out = 포기해 오류 행을 쓴 모델 수 — run은
    그대로 completed. 모델별 상한은 워커 시작 시점부터 PROBE_FUTURE_TIMEOUT_S, 사이클 전체 상한은
    CYCLE_DEADLINE_SECONDS(시작 못한 대기 모델 포함).
    """
    failed = timed_out = 0
    cycle_deadline = time.monotonic() + CYCLE_DEADLINE_SECONDS
    while pending:
        done, _ = wait(list(pending), timeout=_CYCLE_POLL_SECONDS, return_when=FIRST_COMPLETED)
        for future in done:
            slot = pending.pop(future)
            exc = future.exception()
            if exc is not None:
                failed += 1
                logger.error("AutoProber: model probe failed (%s)", slot.model_id, exc_info=exc)
        now = time.monotonic()
        for future, slot in list(pending.items()):
            started = slot.started_at
            if started is not None and now - started >= PROBE_FUTURE_TIMEOUT_S:
                reason = f"probe did not finish within {PROBE_FUTURE_TIMEOUT_S:g}s (cycle timeout)"
            elif now >= cycle_deadline:
                verb = "did not finish" if started is not None else "not started"
                reason = f"probe {verb} before the {CYCLE_DEADLINE_SECONDS:g}s cycle deadline (cycle timeout)"
            else:
                continue
            del pending[future]
            future.cancel()  # 아직 대기 중이면 실행되지 않는다. 실행 중이면 무효 — 스레드는 버린다.
            if not slot.abandon():
                continue  # 방금 워커가 자기 행을 커밋했다 — 쓸 것이 없다
            timed_out += 1
            logger.warning("AutoProber: %s — %s; recording an error row", slot.model_id, reason)
            if not _record_unfinished_probe(run_id, slot, prompt, category, reason):
                failed += 1
    return failed, timed_out


def _run_reserved_cycle(run_id: int, preset: dict) -> int:
    auto_prober.current_cycle_running = True
    cur_prompt = preset["prompt"]
    cur_max_tokens = preset["max_tokens"]
    cur_category = preset["id"]
    logger.info("AutoProber: starting probe cycle (preset=%s, max_tokens=%d)", cur_category, cur_max_tokens)

    event_queue: Queue = Queue()
    try:
        plan = _plan_cycle(run_id, preset, dict(AVAILABLE_MODELS))
    except Exception:
        auto_prober.current_cycle_running = False
        _set_run_status(run_id, "failed")
        raise

    # 각 probe는 자신의 DB 세션을 worker 안에서 생성하고 finally에서 즉시 닫는다.
    # 과거 버그(2026-06-09): 모델당 SessionLocal()을 submit 루프에서 미리 만들고 in-order
    # 결과 루프에서야 close → 느린 probe 하나(예: Opus 4.8 Global read-timeout)가 루프를
    # 막으면 완료된 세션들의 connection이 쌓여 pool(5+5=10)을 고갈시킴(commit 후 db.refresh가
    # read 트랜잭션을 close까지 유지). 모델 수 12→15 확장으로 한계를 넘어 tail 모델들이
    # "QueuePool limit reached"로 persist 실패. 세션 수명을 worker 실행에 묶어 동시
    # connection 수를 max_workers로 제한 → 모델 수와 무관하게 안전.
    def _probe_worker(slot: _ProbeSlot, client) -> None:
        if not slot.begin():
            return  # 시작 전에 사이클이 포기함 — 오류 행은 사이클이 이미 썼다
        model_preset = slot.preset or preset  # 모델별 preset (CP 채널은 자기 회전, v2.29.0)
        thread_db = SessionLocal()
        try:
            _probe_single_model(
                client,
                slot.model_id,
                slot.model_name,
                model_preset["prompt"],
                0.1,
                model_preset["max_tokens"],
                1,
                event_queue,
                run_id,
                _SlotSession(thread_db, slot),
                model_preset["id"],  # category 전달
            )
        finally:
            thread_db.close()

    # context manager(with) 대신 명시적 shutdown (v2.28.2): with 종료는 모든 워커 스레드를 join해서,
    # 멈춘 프로브 스레드 하나가 사이클 종료와 Fargate 태스크 종료를 30~46분 붙잡았다(2026-09-23 장애).
    executor = ThreadPoolExecutor(max_workers=3)
    slots: list[_ProbeSlot] = []
    try:
        pending: dict[Future, _ProbeSlot] = {}
        for model_id, model_name, model_preset in plan:
            client = _get_bedrock_client(_get_region_for_model(model_id))
            slot = _ProbeSlot(model_id, model_name, model_preset)
            slots.append(slot)
            pending[executor.submit(_probe_worker, slot, client)] = slot

        failed_probes, timed_out = _await_probes(pending, run_id, cur_prompt, cur_category)
        if failed_probes:
            raise RuntimeError(f"{failed_probes} model probes did not finish normally")
        if timed_out:
            logger.warning(
                "AutoProber: %d model probe(s) timed out — recorded as error rows, run completes", timed_out,
            )
        _set_run_status(run_id, "completed")
    except Exception:
        # 실패한 run 뒤에 남은 워커가 행을 쓰지 않게 전부 포기 처리한다 (커밋은 롤백으로 바뀐다).
        for slot in slots:
            slot.abandon()
        _set_run_status(run_id, "failed")
        raise
    finally:
        # 멈춘 스레드를 기다리지 않는다 — 대기 중 작업은 취소, 실행 중 스레드는 버린다(자기 socket
        # timeout이나 watchdog으로 풀리면 스스로 끝난다). Fargate 러너는 사이클 뒤 os._exit로 끝낸다.
        executor.shutdown(wait=False, cancel_futures=True)
        auto_prober.current_cycle_running = False

    # 데이터 보존 정책 (v2.7.0): 보존 기간 초과 원본을 시간 집계로 이관 후 삭제.
    # 실패해도 probe cycle 자체는 성공으로 유지 — 다음 cycle에서 재시도된다.
    try:
        from retention import apply_retention

        retention_db = SessionLocal()
        try:
            apply_retention(retention_db)
        finally:
            retention_db.close()
    except Exception:
        logger.exception("AutoProber: retention pass failed (non-fatal)")

    auto_prober.last_run_time = datetime.now(timezone.utc)
    auto_prober.current_cycle_running = False
    logger.info("AutoProber: cycle completed (run_id=%d)", run_id)
    return run_id


# 싱글톤 — 트리거 endpoint가 in-process status를 읽는 용도.
auto_prober = AutoProber()
