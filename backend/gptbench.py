"""GPT on AWS 벤치 사이클 — Bedrock Mantle 3P의 GPT 채널 TTFB/TTFT 정밀 측정 (v2.18.0).

docs/benchmarks/ttft_bench_n20.py 방법론을 상시 스케줄화한 것:
  TTFB = 요청→첫 스트림 이벤트, TTFT = 요청→첫 output_text.delta, GAP = TTFT−TTFB ≈ thinking.
  ~55.8k 토큰 고정 프롬프트(prompt cache 유도), 채널당 RUNS회 **순차** 호출 (병렬화 금지 —
  contention이 레이턴시를 왜곡, 벤치 방법론과 동일 이유).

auto_prober와 분리된 이유: 측정 지표가 다름(TTFB/GAP은 프로브에 없음) + 고정 대형 프롬프트
비용 프로파일이 달라 독립 테이블(gpt_bench_results)/스케줄(rate 15 min)로 운영.

EventBridge Scheduler가 15분마다 gptbench_runner --once 로 기동 (NOT daemon).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

RUNS_PER_CHANNEL = int(os.environ.get("GPT_BENCH_RUNS", "10"))
CALL_TIMEOUT_S = float(os.environ.get("GPT_BENCH_CALL_TIMEOUT", "90"))
# 사이클 전체 데드라인 — 15분 스케줄 겹침 방지 (초과 시 남은 채널 skip).
CYCLE_DEADLINE_S = float(os.environ.get("GPT_BENCH_DEADLINE", "780"))  # 13 min

INSTRUCTIONS = "You are a precise technical assistant. Answer in one short sentence."

# (family, model-id env var, 제공 리전) — prober._OPENAI_MODEL_SPECS의 3P(Mantle) 서브셋.
# GPT 5.6 Sol/Luna는 대상 아님 (사용자 지정: 5.4 / 5.5 / 5.6 Terra).
_BENCH_SPECS: list[tuple[str, str, tuple[str, ...]]] = [
    ("GPT 5.4", "BEDROCK_OPENAI_GPT_54_MODEL_ID", ("us-east-1", "us-east-2", "us-west-2")),
    ("GPT 5.5", "BEDROCK_OPENAI_GPT_55_MODEL_ID", ("us-east-1", "us-east-2")),
    ("GPT 5.6 Terra", "BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID", ("us-east-1", "us-east-2", "us-west-2")),
]

# ~55.8k 토큰 고정 컨텍스트 — 벤치 스크립트와 동일 (변경 시 캐시 무효 + 측정 연속성 깨짐 주의).
_PARA = (
    "In distributed observability, tail latency dominates user-perceived performance; "
    "time-to-first-byte and time-to-first-token diverge sharply for reasoning models "
    "because the server emits an acknowledgment before it finishes its hidden chain of "
    "thought, and only afterwards streams the first visible text delta to the client. "
)
_BIG = "".join(f"[Section {i:04d}] {_PARA}" for i in range(900))
_INPUT = [{"role": "user", "content": _BIG +
           "\n\nQuestion: In one sentence, what is the single most important idea above?"}]

_EXTRA = {
    "text": {"format": {"type": "text"}, "verbosity": "low"},
    "reasoning": {"effort": "medium"},
    "include": ["reasoning.encrypted_content"],
    "store": False,
    "prompt_cache_retention": "24h",
}

_client_cache: dict[str, object] = {}


def _client_for(region: str):
    """리전별 Mantle OpenAI 클라이언트 (prober와 동일한 env 규약)."""
    from prober import _openai_base_url  # 지연 import — 등록 부작용 없음

    base_url = _openai_base_url(region)
    if base_url not in _client_cache:
        from openai import OpenAI
        _client_cache[base_url] = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=base_url,
            timeout=CALL_TIMEOUT_S,
        )
    return _client_cache[base_url]


def bench_channels() -> list[dict]:
    """env로 활성화된 (family, region, actual_id) 채널 목록 — Mantle 키 없으면 빈 목록."""
    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY not set - GPT bench skipped")
        return []
    chans = []
    for family, env_var, regions in _BENCH_SPECS:
        actual_id = os.environ.get(env_var)
        if not actual_id:
            continue
        for region in regions:
            if not os.environ.get({
                "us-east-1": "OPENAI_US_EAST_1_BASE_URL",
                "us-east-2": "OPENAI_US_EAST_2_BASE_URL",
                "us-west-2": "OPENAI_US_WEST_2_BASE_URL",
            }[region]):
                continue
            chans.append(dict(
                family=family, region=region, actual_id=actual_id,
                model_id=f"openai:{region}:{actual_id}",
                model_name=f"OpenAI {family} ({region})",
            ))
    return chans


def one_call(region: str, actual_id: str) -> dict:
    """단일 스트리밍 호출 — TTFB/TTFT/usage 수집 (벤치 스크립트 one_call과 동일 로직)."""
    client = _client_for(region)
    t0 = time.perf_counter()
    ttfb = ttft = None
    cached = reasoning = out_tok = in_tok = None
    err = None
    try:
        stream = client.responses.create(
            model=actual_id, input=_INPUT, instructions=INSTRUCTIONS,
            max_output_tokens=4096, stream=True, extra_body=_EXTRA,
        )
        for ev in stream:
            now = time.perf_counter()
            et = getattr(ev, "type", "")
            if ttfb is None:
                ttfb = (now - t0) * 1000.0
            if et == "response.output_text.delta" and ttft is None:
                ttft = (now - t0) * 1000.0
            if et in ("response.completed", "response.incomplete", "response.failed"):
                u = getattr(getattr(ev, "response", None), "usage", None)
                if u is not None:
                    in_tok = getattr(u, "input_tokens", None)
                    out_tok = getattr(u, "output_tokens", None)
                    itd = getattr(u, "input_tokens_details", None)
                    cached = getattr(itd, "cached_tokens", None) if itd else None
                    otd = getattr(u, "output_tokens_details", None)
                    reasoning = getattr(otd, "reasoning_tokens", None) if otd else None
    except Exception as e:  # noqa: BLE001 — 개별 호출 실패는 row로 기록하고 계속
        err = f"{type(e).__name__}: {str(e)[:300]}"
    return dict(ttfb_ms=ttfb, ttft_ms=ttft, cached_tokens=cached,
                reasoning_tokens=reasoning, output_tokens=out_tok,
                input_tokens=in_tok, error=err)


def run_cycle() -> dict:
    """1 사이클 = 활성 채널 × RUNS_PER_CHANNEL 순차 호출 → gpt_bench_results 저장.

    반환: {"cycle_ts", "channels", "rows", "errors", "skipped_channels"}.
    """
    from database import SessionLocal
    from models import GptBenchResult

    cycle_ts = datetime.now(timezone.utc)
    started = time.perf_counter()
    chans = bench_channels()
    logger.info("GPT bench cycle start: %d channels x %d runs", len(chans), RUNS_PER_CHANNEL)

    rows = errors = 0
    skipped: list[str] = []
    db = SessionLocal()
    try:
        for ch in chans:
            if time.perf_counter() - started > CYCLE_DEADLINE_S:
                skipped.append(ch["model_name"])
                logger.warning("cycle deadline exceeded - skipping %s", ch["model_name"])
                continue
            # 워밍업 1회 (connection/TLS·캐시 안정화) — 저장하지 않음, 벤치 방법론 동일.
            one_call(ch["region"], ch["actual_id"])
            for run_no in range(1, RUNS_PER_CHANNEL + 1):
                if time.perf_counter() - started > CYCLE_DEADLINE_S:
                    skipped.append(f"{ch['model_name']} (run {run_no}+)")
                    break
                r = one_call(ch["region"], ch["actual_id"])
                gap = (r["ttft_ms"] - r["ttfb_ms"]) if (r["ttft_ms"] and r["ttfb_ms"]) else None
                db.add(GptBenchResult(
                    cycle_ts=cycle_ts,
                    timestamp=datetime.now(timezone.utc),
                    model_id=ch["model_id"],
                    model_name=ch["model_name"],
                    family=ch["family"],
                    region=ch["region"],
                    run_no=run_no,
                    status="error" if r["error"] else "success",
                    ttfb_ms=r["ttfb_ms"],
                    ttft_ms=r["ttft_ms"],
                    gap_ms=gap,
                    input_tokens=r["input_tokens"],
                    cached_tokens=r["cached_tokens"],
                    reasoning_tokens=r["reasoning_tokens"],
                    output_tokens=r["output_tokens"],
                    error_message=r["error"],
                ))
                rows += 1
                if r["error"]:
                    errors += 1
            db.commit()  # 채널 단위 커밋 — 부분 실패에도 완료 채널은 보존
            logger.info("channel done: %s", ch["model_name"])
    finally:
        db.close()

    elapsed = time.perf_counter() - started
    logger.info("GPT bench cycle done: rows=%d errors=%d skipped=%s elapsed=%.0fs",
                rows, errors, skipped or "none", elapsed)
    return dict(cycle_ts=cycle_ts.isoformat(), channels=len(chans),
                rows=rows, errors=errors, skipped_channels=skipped)
