"""인사이트 도출 잡 — EventBridge Scheduler가 5분마다 호출(rate(5 minutes)).

흐름:
  1. 최근 N시간(기본 6h) 자동 run의 ProbeResult에서 통계에 쓰는 다섯 열만 나눠 읽는다. 읽은 세션은 닫는다.
  2. 모델별 stats 계산 (avg/p50/p95/err_rate).
  3. Sonnet 4.6에 요약 프롬프트 + stats를 전달, KO와 EN 마크다운 요약을 동시에 스트리밍으로 받는다.
  4. 새 세션의 짧은 트랜잭션으로 Insight 테이블에 INSERT.

ECS Task Definition CMD:
  python -m insights_runner --window 6h

메모리 (2026-09-30 /analysis OOM 후속): run_once와 collect_stats_for_window는 POST /api/insights/regenerate,
/stream-regenerate가 backend 프로세스 안에서도 부른다. 예전에는 ProbeResult 엔티티(prompt, output_text 포함)를 .all()로
적재했고, run_once의 ProbeRun 엔티티 조회는 ProbeRun.results(lazy="selectin")로 그 run들의 결과 엔티티를 한 번 더
끌어왔다. 지금은 run id만, 결과는 _STATS_COLUMNS만 yield_per로 읽는다. API의 창 상한(24h)은 routers/insights.py에 있다.

시간 상한: yield_per는 PostgreSQL에서 서버 측 커서라 statement_timeout이 FETCH마다 따로 걸린다. 두 통계 조회는
streamed_read.stream_rows로 전체 경과 시간을 같은 상한(DB_STATEMENT_TIMEOUT_MS, 기본 30초)에 묶고, 넘으면 커서를 닫고
StreamedReadTimeout을 던진다 — run_once는 except에서 -1(CLI exit 1), stream-regenerate는 error 이벤트로 처리한다.

락 (v2.32.2, 2026-09-30): 요약 동안 DB 트랜잭션을 쥐지 않는다. 예전에는 통계를 읽은 세션을 저장까지 열어 두어
probe_runs, probe_results의 ACCESS SHARE 락이 요약 내내(2~7분) 남았고, backend 기동의 `ALTER TABLE … ADD COLUMN IF NOT
EXISTS`(ACCESS EXCLUSIVE)가 lock_timeout 5초 뒤 LockNotAvailable로 실패했다(기동 네 번 중 두 번).

Bedrock 호출 (v2.32.2, 2026-09-30): 비스트림 converse는 생성이 끝나야 첫 바이트가 와서, 요약 5.4k~6.3k토큰(55~75초)이
기본 read timeout 60초에 자주 걸렸다(EN 24시간 109/279건 실패, legacy 재시도 5회로 태스크 6~7분 → 5분 주기와 겹침).
지금은:
  - agent.bedrock.insights_client(connect 10초, read 60초, standard 재시도 2회)로 converse_stream을 받는다
    (converse_stream_collect). read timeout은 청크 사이 대기 상한이고, 호출 전체는 wall-clock 상한으로 끊는다.
  - 호출 상한 = min(INSIGHTS_CALL_WALL_CLOCK_S(기본 180초 — max_tokens 8192를 정상 처리량의 절반, 초당 약 45토큰으로
    만드는 시간), 마감 − 지금 − _SAVE_MARGIN_S). 마감은 CLI만 건다: main()이 INSIGHTS_TASK_BUDGET_S(기본 240초) 뒤로
    잡고, 마감 + _BACKSTOP_GRACE_S에 백스톱 타이머가 exit 1로 프로세스를 끝낸다. /regenerate 스레드는 마감이 없다.
  - KO와 EN을 워커 두 개로 동시에 만든다. 프롬프트는 메인 스레드에서 KO, EN 순서로 만든다(바이트 단위로 예전과 같다).
    KO가 실패하면 저장하지 않고(-1), EN이 실패하면 KO만 저장한다.
  - 스트림이 열린 뒤 끊기면(StreamInterrupted) 호출 상한이 _RETRY_MIN_S 이상 남았을 때만 한 번 다시 부른다. 끊긴 시도의
    텍스트는 버린다. wall-clock 만료는 다시 부르지 않는다(두 번째 생성이 예산에 들어가지 않는다).
  - 언어마다 소요 시간, output_tokens, input_tokens, stop_reason을 INFO로 남기고, max_tokens에서 멈추면 WARNING이다.
  - CLI는 os._exit로 끝낸다(_finish) — 인터프리터 종료가 멈춘 워커 스레드를 join해 태스크를 RUNNING으로 붙잡지 않게.
    run_once 안에서는 os._exit를 쓰지 않는다(backend의 /regenerate 스레드도 이 함수를 쓴다).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List

from database import SessionLocal
from models import Insight, ProbeResult, ProbeRun
from streamed_read import stream_rows
from visibility import visible_only

_PROCESS_STARTED = time.monotonic()  # 태스크 예산의 기준 — `python -m insights_runner`에서는 import 직후 = 프로세스 시작 약 1초 뒤
logger = logging.getLogger(__name__)

# compute_stats가 읽는 속성 전부 — 이 밖의 열(prompt, output_text, error_message …)은 읽지 않는다.
_STATS_COLUMNS = (
    ProbeResult.model_name,
    ProbeResult.status,
    ProbeResult.ttft_ms,
    ProbeResult.total_latency_ms,
    ProbeResult.tps,
)
_YIELD_PER = 2000  # 한 번에 가져오는 행 수(PostgreSQL은 서버 측 커서 — 전체 시간 상한은 streamed_read)

# 요약 호출 (v2.32.2) — 모듈 docstring의 "Bedrock 호출" 참고.
INSIGHTS_CALL_WALL_CLOCK_S = float(os.environ.get("INSIGHTS_CALL_WALL_CLOCK_S", "180"))
INSIGHTS_TASK_BUDGET_S = float(os.environ.get("INSIGHTS_TASK_BUDGET_S", "240"))  # CLI만, 프로세스 시작부터
_SAVE_MARGIN_S = 15.0  # 마감 전에 저장할 시간
_MIN_CALL_S = 30.0  # 호출 상한이 이보다 짧으면 부르지 않는다(생성이 끝날 수 없다)
_RETRY_MIN_S = 90.0  # 끊긴 스트림은 호출 상한이 이만큼 남았을 때만 다시 부른다(정상 생성 p50 약 70초)
_CALL_ATTEMPTS = 2  # 언어당 converse_stream 호출 수(재시도 포함). 헤더 대기 재시도는 botocore가 따로 한다
_BACKSTOP_GRACE_S = 15.0
_MAX_TOKENS = 8192
_TEMPERATURE = 0.1
_LANGS = ("ko", "en")  # 프롬프트를 만들고 제출하는 순서
_clock = time.monotonic


class InsightsBudgetExhausted(Exception):
    """태스크 예산이 모자라 요약을 부르지 않았다."""


def parse_window(spec: str) -> timedelta:
    """'6h', '24h', '3d' 같은 입력 파싱."""
    m = re.match(r"^(\d+)([hd])$", spec.strip().lower())
    if not m:
        raise ValueError("--window는 '6h', '24h', '3d' 형식이어야 합니다")
    n = int(m.group(1))
    unit = m.group(2)
    return timedelta(hours=n) if unit == "h" else timedelta(days=n)


def compute_stats(rows: Iterable[Any]) -> Dict[str, Any]:
    """모델별 ttft/total_latency/tps 통계 + 에러율.

    rows는 한 번만 돈다. 각 행은 model_name, status, ttft_ms, total_latency_ms, tps 속성을 가진다
    (_stats_query의 열 조회 행 또는 ProbeResult). 모델 순서는 행에서 처음 나온 순서다.
    """
    by_model: Dict[str, List[Any]] = {}
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


def _call_limit(deadline: float | None) -> float:
    """이번 호출의 wall-clock 상한(초) — 마감이 있으면 저장 여유를 남긴 나머지로 줄인다."""
    if deadline is None:
        return INSIGHTS_CALL_WALL_CLOCK_S
    return min(INSIGHTS_CALL_WALL_CLOCK_S, deadline - _clock() - _SAVE_MARGIN_S)


def _summarize_prompt(client, lang: str, system: str, user_text: str, deadline: float | None) -> str:
    """언어 하나의 요약 — converse_stream, 호출마다 wall-clock 상한, 스트림이 끊기면 예산 안에서 한 번 더."""
    from agent import bedrock

    started = _clock()
    for attempt in range(1, _CALL_ATTEMPTS + 1):
        limit = _call_limit(deadline)
        if limit < _MIN_CALL_S:
            logger.warning("insights summary %s: %.1fs left for the call (< %gs), not calling Bedrock",
                           lang, limit, _MIN_CALL_S)
            raise InsightsBudgetExhausted(f"{lang}: {limit:.1f}s left for the call")
        try:
            result = bedrock.converse_stream_collect(
                messages=[{"role": "user", "content": [{"text": user_text}]}],
                model_id=bedrock.INSIGHTS_MODEL_ID,
                system=system,
                max_tokens=_MAX_TOKENS,
                temperature=_TEMPERATURE,
                wall_clock_s=limit,
                client=client,
            )
        except bedrock.StreamInterrupted as exc:
            if attempt < _CALL_ATTEMPTS and _call_limit(deadline) >= _RETRY_MIN_S:
                logger.warning("insights summary %s: %s, retrying (attempt %d/%d)", lang, exc, attempt + 1, _CALL_ATTEMPTS)
                continue
            logger.warning("insights summary %s failed after %.1fs (attempt %d): %s", lang, _clock() - started, attempt, exc)
            raise
        except Exception as exc:
            logger.warning("insights summary %s failed after %.1fs (attempt %d): %s: %s",
                           lang, _clock() - started, attempt, type(exc).__name__, exc)
            raise
        logger.info("insights summary %s: %.1fs, output_tokens=%s, input_tokens=%s, stop_reason=%s, chars=%d, attempts=%d",
                    lang, _clock() - started, result.output_tokens, result.input_tokens, result.stop_reason,
                    len(result.text), attempt)
        if result.stop_reason == "max_tokens":
            logger.warning("insights summary %s stopped at max_tokens (%d), the saved summary may be cut off",
                           lang, _MAX_TOKENS)
        return result.text
    raise AssertionError("unreachable")  # pragma: no cover — 루프는 return이나 raise로 끝난다


def _summarize(window_label: str, stats: Dict[str, Any], lang: str, *, client=None,
               deadline: float | None = None) -> str:
    """Sonnet 4.6 요약 하나 — lang in {'ko','en'}. 프롬프트는 _build_prompt와 같다."""
    from agent import bedrock

    system, user_text = _build_prompt(window_label, stats, lang)
    return _summarize_prompt(client if client is not None else bedrock.insights_client(), lang, system, user_text,
                             deadline)


def summarize_with_bedrock(window_label: str, stats: Dict[str, Any]) -> str:
    """KO 요약 - 기존 인터페이스 유지 (legacy callers)."""
    return _summarize(window_label, stats, "ko")


def _result(future, lang: str, deadline: float | None) -> str:
    """워커 결과 — 마감이 있으면 마감까지만 기다린다.

    호출의 wall-clock 상한은 스트림이 열린 뒤에만 끊을 수 있다. 재시도가 헤더 대기(connect + read timeout, botocore 2회)에서
    마감을 넘기면 워커를 두고 마감에서 포기한다 — 저장 여유(_SAVE_MARGIN_S)와 백스톱 유예 안에서 저장하게.
    """
    timeout = None if deadline is None else max(0.0, deadline - _clock())
    try:
        return future.result(timeout=timeout)
    except TimeoutError as exc:  # concurrent.futures.TimeoutError는 3.11부터 내장 TimeoutError다
        raise InsightsBudgetExhausted(f"{lang} summary did not finish before the task deadline") from exc


def _summarize_both(window_label: str, stats: Dict[str, Any], deadline: float | None) -> tuple[str, str | None]:
    """KO와 EN을 동시에 만든다. KO 실패는 그대로 던지고, EN 실패는 로그를 남기고 None."""
    from agent import bedrock

    prompts = {lang: _build_prompt(window_label, stats, lang) for lang in _LANGS}  # 메인 스레드에서 KO, EN 순서
    client = bedrock.insights_client()  # 호출 스레드에서 한 번 — 두 워커가 같이 쓴다
    pool = ThreadPoolExecutor(max_workers=len(_LANGS), thread_name_prefix="insights-summary")
    try:
        futures = {lang: pool.submit(_summarize_prompt, client, lang, *prompts[lang], deadline) for lang in _LANGS}
        summary_ko = _result(futures["ko"], "ko", deadline)  # 실패하면 EN을 기다리지 않는다 — run_once가 -1
        try:
            summary_en = _result(futures["en"], "en", deadline)
        except Exception:
            # 영어 요약 실패해도 한국어는 살린다.
            logger.exception("EN insight generation failed; KO만 저장")
            summary_en = None
        return summary_ko, summary_en
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # 남은 워커는 자기 상한으로 끝난다(CLI는 _finish의 os._exit)


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


def _stats_query(db):
    """숨김 라벨을 뺀 ProbeResult의 _STATS_COLUMNS 조회 — 엔티티를 만들지 않는다."""
    return visible_only(db.query(*_STATS_COLUMNS), ProbeResult.model_name)


def collect_stats_for_window(db, window_spec: str) -> Dict[str, Any]:
    """주어진 window의 stats만 계산 (DB session 주입식, SSE에서 사용)."""
    delta = parse_window(window_spec)
    since = datetime.now(timezone.utc) - delta
    rows = _stats_query(db).filter(ProbeResult.timestamp >= since).yield_per(_YIELD_PER)
    return compute_stats(stream_rows(rows, what=f"insights_runner.collect_stats_for_window window={window_spec!r}"))


def _read_stats(window_spec: str, cutoff: datetime) -> Dict[str, Any] | None:
    """창 안 자동 run의 통계. 없으면 None(로그를 남긴다).

    읽은 세션은 돌아가기 전에 닫는다 — 읽기 트랜잭션이 끝나고 커넥션이 풀로 돌아가므로, 이어지는 Bedrock 요약(KO, EN) 동안
    probe_runs, probe_results의 ACCESS SHARE 락과 커넥션을 쥐지 않는다(v2.32.2). 예전에는 이 세션을 저장까지 열어 두어
    backend 기동의 `ALTER TABLE probe_runs ADD COLUMN IF NOT EXISTS …`(ACCESS EXCLUSIVE)가 lock_timeout 5초 뒤
    LockNotAvailable로 실패했다(2026-09-30, 기동 네 번 중 두 번).
    """
    db = SessionLocal()
    try:
        # id만 읽는다 — ProbeRun 엔티티는 results(lazy="selectin")로 그 run들의 ProbeResult 엔티티를 함께 끌어온다.
        run_ids = [
            run_id
            for (run_id,) in db.query(ProbeRun.id).filter(
                ProbeRun.is_auto == 1,
                ProbeRun.status == "completed",
                ProbeRun.created_at >= cutoff,
            )
        ]
        if not run_ids:
            logger.info("최근 %s 동안 auto run 없음 - insight skip", window_spec)
            return None

        stats = compute_stats(stream_rows(
            _stats_query(db).filter(ProbeResult.run_id.in_(run_ids)).yield_per(_YIELD_PER),
            what=f"insights_runner.run_once window={window_spec!r}",
        ))
        if not stats:  # 결과 행이 없거나 모두 숨김 라벨
            logger.info("ProbeResult 없음 - insight skip")
            return None
        return stats
    finally:
        db.close()


def _save_insight(window_start: datetime, window_end: datetime, summary_ko: str, summary_en: str | None,
                  stats: Dict[str, Any]) -> int:
    """요약이 끝난 뒤 새 세션의 짧은 트랜잭션 하나로 저장한다. 반환값: insight id."""
    db = SessionLocal()
    try:
        insight = Insight(
            window_start=window_start,
            window_end=window_end,
            summary_md=summary_ko,
            summary_md_en=summary_en,
            model_breakdown=stats,
        )
        db.add(insight)
        db.flush()
        insight_id = insight.id
        db.commit()
        return insight_id
    finally:
        db.close()


def run_once(window_spec: str = "6h", *, deadline: float | None = None) -> int:
    """한 번 실행하고 종료. 반환값: 생성된 insight ID (0 = skip, -1 = 실패).

    세션 순서(v2.32.2): 통계를 읽은 세션을 닫고 → Bedrock 요약(KO, EN 동시) → 새 세션으로 저장. 요약 동안 DB 트랜잭션이
    없다. deadline(time.monotonic 기준)은 CLI의 태스크 예산 마감이다 — 없으면 호출마다 INSIGHTS_CALL_WALL_CLOCK_S만 건다.
    """
    try:
        window = parse_window(window_spec)
    except ValueError as exc:
        logger.error("%s", exc)
        return -1

    now = datetime.now(timezone.utc)
    cutoff = now - window

    try:
        stats = _read_stats(window_spec, cutoff)
        if stats is None:
            return 0

        # 한국어와 영어 두 요약을 한 번에 생성 (UI 언어 토글 즉시 반영용).
        summary_ko, summary_en = _summarize_both(window_spec, stats, deadline)

        insight_id = _save_insight(cutoff, now, summary_ko, summary_en, stats)
        logger.info("insights_runner: insight id=%d 저장 (window=%s)", insight_id, window_spec)
        return insight_id
    except Exception:
        logger.exception("insights_runner 실패")
        return -1


def main(started_at: float | None = None) -> int:
    """CLI 진입점 - EventBridge Scheduler가 호출하는 Fargate task용.

    태스크 예산: started_at(기본 지금 — `python -m`은 _PROCESS_STARTED를 넘긴다) + INSIGHTS_TASK_BUDGET_S가 요약 호출의
    마감이다. 마감 + _BACKSTOP_GRACE_S가 지나도 run_once가 돌아오지 않으면 백스톱이 exit 1로 프로세스를 끝낸다.
    """
    started = _clock() if started_at is None else started_at
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Insight 도출 잡 - 한 번 실행 후 종료")
    parser.add_argument("--window", default="6h", help="분석 윈도우 (예: 6h, 24h, 3d)")
    args = parser.parse_args()

    deadline = started + INSIGHTS_TASK_BUDGET_S
    backstop = threading.Timer(max(0.0, deadline - _clock()) + _BACKSTOP_GRACE_S, _backstop,
                               args=(INSIGHTS_TASK_BUDGET_S, _BACKSTOP_GRACE_S))
    backstop.daemon = True
    backstop.start()
    try:
        result = run_once(args.window, deadline=deadline)
    finally:
        backstop.cancel()
    return 0 if result >= 0 else 1


_hard_exit = os._exit  # 테스트가 바꾼다


def _flush_logs() -> None:
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:  # noqa: BLE001 — 종료 경로는 어떤 정리 실패에도 막히지 않는다
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001
            pass


def _backstop(budget_s: float, grace_s: float) -> None:
    """예산 + 유예가 지났다 — 요약이 돌아오기를 기다리지 않고 exit 1(다음 스케줄 태스크와 겹치지 않게)."""
    logger.error("insights_runner: task budget %gs + %gs grace passed, exiting 1 without waiting for the summaries",
                 budget_s, grace_s)
    _flush_logs()
    _hard_exit(1)


def _finish(exit_code: int, _exit=os._exit) -> None:
    """남은 스레드를 기다리지 않고 프로세스를 끝낸다 — auto_prober_runner._finish와 같다(v2.28.2).

    sys.exit()는 인터프리터 종료 단계에서 ThreadPoolExecutor 워커를 join한다. 요약 워커가 헤더 대기에서 멈춰 있으면
    Fargate 태스크가 RUNNING으로 남는다. 그래서 DB 엔진을 정리하고 로그를 flush한 뒤 os._exit로 끝낸다. exit code는
    그대로다: 0 = 저장 또는 skip, 1 = 실패.
    """
    try:
        from database import engine

        engine.dispose()
    except Exception:  # noqa: BLE001
        logging.exception("insights_runner: engine dispose failed (ignored)")
    logging.shutdown()
    _flush_logs()
    _exit(exit_code)


def _entrypoint() -> None:
    _finish(main(started_at=_PROCESS_STARTED))


if __name__ == "__main__":
    _entrypoint()
