"""패리티 런 오케스트레이터 (v2.11.0).

모델 × surface × 피처 매트릭스를 팬아웃해 실제 프로브를 실행하고 결과를 RDS에 저장한다.
- 대상 모델: prober.AVAILABLE_MODELS (모니터링 카탈로그와 동일 — 신규 모델 자동 반영)
- 동시성: ThreadPoolExecutor(4) — auto_prober와 같은 패턴 (스레드별 자체 DB 세션 금지,
  결과는 메인 스레드에서 일괄 저장해 커넥션 풀 부담 최소화)
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from database import SessionLocal
from models import ParityResult, ParityRun
from parity.catalog import FEATURE_IDS, is_applicable, mantle_fm_id, surfaces_for
from parity.probes import (
    ProbeOutcome,
    probe_chat_completions,
    probe_converse,
    probe_invoke_model,
    probe_messages,
    probe_responses,
)

logger = logging.getLogger(__name__)

_MAX_WORKERS = 4
_PROBE_TIMEOUT_S = 120


def _execute(model_id: str, surface: str, feature: str) -> ProbeOutcome:
    """surface에 맞는 클라이언트를 준비해 프로브 1건 실행."""
    from prober import (  # 지연 import — 클라이언트 헬퍼 재사용
        _anthropic_actual_id,
        _get_anthropic_client,
        _get_bedrock_client,
        _get_openai_client,
        _get_region_for_model,
        _openai_base_url,
        _openai_parts,
    )

    if surface in ("converse", "invoke_model"):
        client = _get_bedrock_client(_get_region_for_model(model_id))
        fn = probe_converse if surface == "converse" else probe_invoke_model
        return fn(client, model_id, feature)
    if surface == "messages":
        return probe_messages(_get_anthropic_client(), _anthropic_actual_id(model_id), feature)
    if surface == "messages_mantle":
        # Bedrock Mantle /anthropic (v2.13.0) — SigV4 파생 bearer + FM id. 리전은 env로 제어.
        import os

        import anthropic
        from aws_bedrock_token_generator import provide_token

        region = os.environ.get("MANTLE_ANTHROPIC_REGION", "ap-northeast-1")
        client = anthropic.Anthropic(
            api_key=provide_token(region=region),
            base_url=f"https://bedrock-mantle.{region}.api.aws/anthropic",
            timeout=60,
            max_retries=1,
        )
        return probe_messages(client, mantle_fm_id(model_id), feature)
    # chat_completions / responses
    region, actual_id = _openai_parts(model_id)
    client = _get_openai_client(_openai_base_url(region))
    fn = probe_chat_completions if surface == "chat_completions" else probe_responses
    return fn(client, actual_id, feature)


def run_parity() -> int:
    """전체 패리티 런 1회 실행. run_id 반환."""
    from prober import AVAILABLE_MODELS

    db = SessionLocal()
    try:
        run = ParityRun(status="running", started_at=datetime.now(timezone.utc))
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    except Exception:
        db.close()
        raise

    # 작업 목록 구성 — skipped는 프로브 없이 기록만.
    jobs: list[tuple[str, str, str, str]] = []  # (model_id, model_name, surface, feature)
    skipped: list[tuple[str, str, str, str]] = []
    for model_id, model_name in AVAILABLE_MODELS.items():
        for surface in surfaces_for(model_id):
            for feature in FEATURE_IDS:
                if is_applicable(feature, surface, model_id):
                    jobs.append((model_id, model_name, surface, feature))
                else:
                    skipped.append((model_id, model_name, surface, feature))

    logger.info("Parity run %d: %d probes (+%d skipped)", run_id, len(jobs), len(skipped))

    results: list[ParityResult] = [
        ParityResult(run_id=run_id, model_id=m, model_name=n, surface=s, feature=f,
                     status="skipped", evidence={})
        for m, n, s, f in skipped
    ]

    counts = {"supported": 0, "unsupported": 0, "broken": 0, "skipped": len(skipped)}
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_execute, m, s, f): (m, n, s, f) for m, n, s, f in jobs}
        done = 0
        for fut in as_completed(futures):
            model_id, model_name, surface, feature = futures[fut]
            try:
                outcome = fut.result(timeout=_PROBE_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001
                outcome = ProbeOutcome("broken", error=f"executor: {exc}")
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            results.append(ParityResult(
                run_id=run_id, model_id=model_id, model_name=model_name,
                surface=surface, feature=feature, status=outcome.status,
                latency_ms=outcome.latency_ms, evidence=outcome.evidence or {},
                error_message=outcome.error,
            ))
            done += 1
            if done % 25 == 0:
                logger.info("Parity run %d: %d/%d done %s", run_id, done, len(jobs), counts)

    try:
        db.add_all(results)
        run = db.query(ParityRun).filter(ParityRun.id == run_id).first()
        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
        run.totals = counts
        db.commit()
        logger.info("Parity run %d completed: %s", run_id, counts)
    finally:
        db.close()
    return run_id
