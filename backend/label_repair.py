"""저장된 probe 행의 model_name을 현행 카탈로그 라벨과 일치시키는 자가 복구 (v2.22.1).

배경 (2026-09-01 실사고): CP on AWS /v1/models가 claude-fable-5-1을 서빙하기 시작하자 구 prober의
substring 매칭("fable-5")이 5.1 id를 Fable 5 라벨로 등록해, model_id=anthropic:claude-fable-5-1 행 53건이
"Anthropic Claude Fable 5 (US)"로 기록됐다. 이력 통계/추이는 model_name 기준이라 5.1 CP가 Fable 5의
중복 항목으로 보였다. main.py의 `_label_renames`(라벨→라벨 치환)는 같은 트랜잭션의 ALTER TABLE이
statement_timeout으로 실패하면서 함께 롤백되는 상태라 여기서 별도 트랜잭션으로 수행한다.

규칙: 카탈로그(AVAILABLE_MODELS)에 있는 model_id의 행은 model_name을 카탈로그 라벨로 맞춘다.
카탈로그에 없는 model_id(제외/휴면 모델 과거 행)는 건드리지 않는다.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_TABLES = ("probe_results", "probe_results_hourly")


def find_label_mismatches(conn, catalog: dict[str, str], table: str) -> list[tuple[str, str, str]]:
    """(model_id, 저장 라벨, 카탈로그 라벨) — 카탈로그 라벨과 다른 (model_id, model_name) 조합만."""
    rows = conn.execute(text(f"SELECT DISTINCT model_id, model_name FROM {table}")).fetchall()
    out: list[tuple[str, str, str]] = []
    for model_id, model_name in rows:
        expected = catalog.get(model_id)
        if expected is not None and model_name != expected:
            out.append((model_id, model_name, expected))
    return out


def repair_model_labels(engine: Engine, catalog: dict[str, str], statement_timeout_ms: int = 60_000) -> int:
    """카탈로그 라벨과 다른 행을 UPDATE. 반환값은 갱신 행 수(전 테이블 합). 실패는 로그만 (non-fatal)."""
    if not catalog:
        return 0
    total = 0
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "postgresql":
                conn.execute(text(f"SET statement_timeout = '{int(statement_timeout_ms)}'"))
            for table in _TABLES:
                for model_id, old_label, new_label in find_label_mismatches(conn, catalog, table):
                    res = conn.execute(
                        text(f"UPDATE {table} SET model_name = :new WHERE model_id = :mid AND model_name = :old"),
                        {"new": new_label, "mid": model_id, "old": old_label},
                    )
                    n = res.rowcount or 0
                    total += n
                    logger.warning(
                        "Label repair: %s model_id=%s %r -> %r (%d rows)", table, model_id, old_label, new_label, n
                    )
    except Exception:
        logger.exception("Label repair failed (non-fatal, backend continues)")
        return total
    if total:
        logger.info("Label repair done: %d rows updated", total)
    return total
