"""데이터 보존 정책 — 원본 probe_results 보존 기간 초과분을 시간 집계로 이관 후 삭제.

배경 (2026-07-09): probe_results가 5분 × 28모델로 무한 성장(22.7만 행 시점에 인덱스
생성이 30초 statement_timeout을 초과하는 등 운영 부담). 모든 화면이 최대 7~30일만
조회하므로 원본은 RETENTION_DAYS(기본 60일)만 유지하고, 이전 데이터는
probe_results_hourly 집계로 보존한다 (토큰 합계 포함 — 비용 재계산 가능).

호출: auto_prober.run_cycle() 말미 (5분마다 — 하루 분량씩 잘게 처리됨).
원자성: 집계 INSERT + 원본 DELETE가 한 트랜잭션 — 중간 실패 시 롤백되어 재시도 안전
(중복 집계 없음). Python 집계로 PG 전용 SQL 회피 (sqlite 테스트 호환, 일 8k행 수준).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from models import ProbeResult, ProbeResultHourly, ProbeRun

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 60


def apply_retention(db, *, retention_days: int | None = None, now: datetime | None = None) -> dict:
    """보존 기간 초과 원본을 시간 버킷으로 집계 이관 후 삭제. 처리 통계를 반환.

    retention_days <= 0 이면 비활성 (아무것도 하지 않음).
    """
    days = (
        retention_days
        if retention_days is not None
        else int(os.environ.get("RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS)))
    )
    noop = {"aggregated_buckets": 0, "deleted_results": 0, "deleted_runs": 0}
    if days <= 0:
        return noop

    now = now or datetime.now(timezone.utc)
    # 정시 경계로 자름 — 부분 시간대 버킷이 생기지 않게.
    cutoff = (now - timedelta(days=days)).replace(minute=0, second=0, microsecond=0)

    # autoprober 러너는 create_tables()를 거치지 않으므로, backend 재배포 전에 이 코드가
    # 먼저 배포되어도 안전하도록 집계 테이블을 멱등 생성 (checkfirst — 카탈로그 조회 1회).
    ProbeResultHourly.__table__.create(bind=db.get_bind(), checkfirst=True)

    rows = (
        db.query(
            ProbeResult.model_id,
            ProbeResult.model_name,
            ProbeResult.category,
            ProbeResult.timestamp,
            ProbeResult.status,
            ProbeResult.ttft_ms,
            ProbeResult.total_latency_ms,
            ProbeResult.tps,
            ProbeResult.input_tokens,
            ProbeResult.output_tokens,
        )
        .filter(ProbeResult.timestamp < cutoff)
        .all()
    )

    buckets: dict[tuple, list] = {}
    for r in rows:
        if r.timestamp is None:
            continue
        bucket_ts = r.timestamp.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault((r.model_id, r.model_name, r.category, bucket_ts), []).append(r)

    def _mean(values):
        vals = [v for v in values if v is not None]
        return (sum(vals) / len(vals)) if vals else None

    def _sum(values):
        vals = [v for v in values if v is not None]
        return sum(vals) if vals else None

    for (model_id, model_name, category, bucket_ts), items in sorted(
        buckets.items(), key=lambda kv: kv[0][3]
    ):
        db.add(ProbeResultHourly(
            bucket_ts=bucket_ts,
            model_id=model_id,
            model_name=model_name,
            category=category,
            cnt=len(items),
            success_cnt=sum(1 for i in items if i.status == "success"),
            avg_ttft_ms=_mean(i.ttft_ms for i in items),
            avg_total_latency_ms=_mean(i.total_latency_ms for i in items),
            avg_tps=_mean(i.tps for i in items),
            sum_input_tokens=_sum(i.input_tokens for i in items),
            sum_output_tokens=_sum(i.output_tokens for i in items),
        ))

    deleted_results = (
        db.query(ProbeResult)
        .filter(ProbeResult.timestamp < cutoff)
        .delete(synchronize_session=False)
    )
    # 결과가 하나도 남지 않은 옛 run만 삭제 — cutoff 경계에 걸친 run의 FK 파손 방지.
    deleted_runs = (
        db.query(ProbeRun)
        .filter(
            ProbeRun.created_at < cutoff,
            ~db.query(ProbeResult.id).filter(ProbeResult.run_id == ProbeRun.id).exists(),
        )
        .delete(synchronize_session=False)
    )
    db.commit()

    stats = {
        "aggregated_buckets": len(buckets),
        "deleted_results": deleted_results,
        "deleted_runs": deleted_runs,
    }
    if deleted_results:
        logger.info("Retention: %s", stats)
    return stats
