"""인사이트 도출 잡 — EventBridge Scheduler가 30분마다 호출.

흐름:
  1. 최근 N시간(기본 6h) ProbeResult 로드.
  2. 모델별 stats 계산 (avg/p50/p95/err_rate).
  3. Sonnet 4.6에 요약 프롬프트 + stats를 전달, 마크다운 요약 수신.
  4. Insight 테이블에 INSERT.

ECS Task Definition CMD:
  python -m insights_runner --window 6h
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database import SessionLocal
from models import Insight, ProbeResult, ProbeRun

logger = logging.getLogger(__name__)


def parse_window(spec: str) -> timedelta:
    """'6h', '24h', '3d' 같은 입력 파싱."""
    m = re.match(r"^(\d+)([hd])$", spec.strip().lower())
    if not m:
        raise ValueError("--window는 '6h', '24h', '3d' 형식이어야 합니다")
    n = int(m.group(1))
    unit = m.group(2)
    return timedelta(hours=n) if unit == "h" else timedelta(days=n)


def compute_stats(rows: List[ProbeResult]) -> Dict[str, Any]:
    """모델별 ttft/total_latency/tps 통계 + 에러율."""
    by_model: Dict[str, List[ProbeResult]] = {}
    for r in rows:
        by_model.setdefault(r.model_name, []).append(r)

    out: Dict[str, Dict[str, Any]] = {}
    for name, items in by_model.items():
        ok = [i for i in items if i.status == "success"]
        err = [i for i in items if i.status != "success"]
        total = len(items)

        def _stats(values: List[float]) -> Dict[str, Any]:
            if not values:
                return {"n": 0}
            s = sorted(values)
            n = len(s)
            return {
                "n": n,
                "avg": round(sum(s) / n, 2),
                "p50": round(s[n // 2], 2),
                "p95": round(s[min(n - 1, int(n * 0.95))], 2),
                "max": round(s[-1], 2),
            }

        out[name] = {
            "total": total,
            "errors": len(err),
            "error_rate": round(len(err) / total, 4) if total else 0.0,
            "ttft_ms": _stats([i.ttft_ms for i in ok if i.ttft_ms is not None]),
            "total_latency_ms": _stats(
                [i.total_latency_ms for i in ok if i.total_latency_ms is not None]
            ),
            "tps": _stats([i.tps for i in ok if i.tps is not None]),
        }
    return out


SUMMARY_SYSTEM_KO = (
    "당신은 AWS Bedrock LLM 성능 데이터를 분석하는 한국어 어시스턴트입니다. "
    "수치는 그대로 인용하고, 추측하지 마세요. 마크다운 표를 활용해 핵심을 한눈에 보여주세요."
)

SUMMARY_SYSTEM_EN = (
    "You are an English-speaking analyst summarizing AWS Bedrock LLM performance data. "
    "Cite numbers verbatim, do not speculate. Use markdown tables so operators can scan at a glance."
)


def _summarize(window_label: str, stats: Dict[str, Any], lang: str) -> str:
    """Sonnet 4.6 블로킹 호출 - lang in {'ko','en'} 별로 system prompt + user prompt 다르게."""
    from agent.bedrock import converse_blocking, INSIGHTS_MODEL_ID

    if lang == "en":
        user_text = (
            f"Below are AWS Bedrock LLM monitoring statistics for the last {window_label} window.\n"
            "Summarize per-model performance and error rates in English. Call out anomalies.\n\n"
            "```json\n"
            f"{json.dumps(stats, ensure_ascii=False, indent=2)}\n"
            "```\n\n"
            "Output: markdown. First line is a one-sentence summary, followed by a per-model table."
        )
        system = SUMMARY_SYSTEM_EN
    else:
        user_text = (
            f"다음은 최근 {window_label} 동안의 Bedrock 모델 모니터링 통계입니다.\n"
            "각 모델의 성능과 에러율을 한국어로 요약하고, 눈에 띄는 이상 징후가 있다면 짚어 주세요.\n\n"
            "```json\n"
            f"{json.dumps(stats, ensure_ascii=False, indent=2)}\n"
            "```\n\n"
            "출력 형식: 마크다운. 첫 줄에 한 문장 요약, 이어서 모델별 표."
        )
        system = SUMMARY_SYSTEM_KO

    return converse_blocking(
        messages=[{"role": "user", "content": [{"text": user_text}]}],
        model_id=INSIGHTS_MODEL_ID,
        system=system,
        max_tokens=2048,
        temperature=0.1,
    )


def summarize_with_bedrock(window_label: str, stats: Dict[str, Any]) -> str:
    """KO 요약 - 기존 인터페이스 유지 (legacy callers)."""
    return _summarize(window_label, stats, "ko")


def _build_prompt(window_label: str, stats: Dict[str, Any], lang: str) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for streaming use."""
    if lang == "en":
        user_text = (
            f"Below are AWS Bedrock LLM monitoring statistics for the last {window_label} window.\n"
            "Summarize per-model performance and error rates in English. Call out anomalies.\n\n"
            "```json\n"
            f"{json.dumps(stats, ensure_ascii=False, indent=2)}\n"
            "```\n\n"
            "Output: markdown. First line is a one-sentence summary, followed by a per-model table."
        )
        return SUMMARY_SYSTEM_EN, user_text
    user_text = (
        f"다음은 최근 {window_label} 동안의 Bedrock 모델 모니터링 통계입니다.\n"
        "각 모델의 성능과 에러율을 한국어로 요약하고, 눈에 띄는 이상 징후가 있다면 짚어 주세요.\n\n"
        "```json\n"
        f"{json.dumps(stats, ensure_ascii=False, indent=2)}\n"
        "```\n\n"
        "출력 형식: 마크다운. 첫 줄에 한 문장 요약, 이어서 모델별 표."
    )
    return SUMMARY_SYSTEM_KO, user_text


def collect_stats_for_window(db, window_spec: str) -> Dict[str, Any]:
    """주어진 window의 stats만 계산 (DB session 주입식, SSE에서 사용)."""
    delta = parse_window(window_spec)
    since = datetime.now(timezone.utc) - delta
    rows = (
        db.query(ProbeResult)
        .filter(ProbeResult.timestamp >= since)
        .all()
    )
    return compute_stats(rows)


def run_once(window_spec: str = "6h") -> int:
    """한 번 실행하고 종료. 반환값: 생성된 insight ID (0 = skip, -1 = 실패)."""
    try:
        window = parse_window(window_spec)
    except ValueError as exc:
        logger.error("%s", exc)
        return -1

    now = datetime.now(timezone.utc)
    cutoff = now - window

    db = SessionLocal()
    try:
        runs = (
            db.query(ProbeRun)
            .filter(
                ProbeRun.is_auto == 1,
                ProbeRun.status == "completed",
                ProbeRun.created_at >= cutoff,
            )
            .all()
        )
        if not runs:
            logger.info("최근 %s 동안 auto run 없음 - insight skip", window_spec)
            return 0

        run_ids = [r.id for r in runs]
        rows = db.query(ProbeResult).filter(ProbeResult.run_id.in_(run_ids)).all()
        if not rows:
            logger.info("ProbeResult 없음 - insight skip")
            return 0

        stats = compute_stats(rows)
        # 한국어와 영어 두 요약을 한 번에 생성 (UI 언어 토글 즉시 반영용).
        summary_ko = _summarize(window_spec, stats, "ko")
        try:
            summary_en = _summarize(window_spec, stats, "en")
        except Exception:
            # 영어 요약 실패해도 한국어는 살린다.
            logger.exception("EN insight generation failed; KO만 저장")
            summary_en = None

        insight = Insight(
            window_start=cutoff,
            window_end=now,
            summary_md=summary_ko,
            summary_md_en=summary_en,
            model_breakdown=stats,
        )
        db.add(insight)
        db.commit()
        db.refresh(insight)
        logger.info("insights_runner: insight id=%d 저장 (window=%s)", insight.id, window_spec)
        return insight.id
    except Exception:
        logger.exception("insights_runner 실패")
        return -1
    finally:
        db.close()


def main() -> int:
    """CLI 진입점 - EventBridge Scheduler가 호출하는 Fargate task용."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Insight 도출 잡 - 한 번 실행 후 종료")
    parser.add_argument("--window", default="6h", help="분석 윈도우 (예: 6h, 24h, 3d)")
    args = parser.parse_args()

    result = run_once(args.window)
    return 0 if result >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
