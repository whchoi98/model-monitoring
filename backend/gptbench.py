"""GPT on AWS 벤치 사이클 — Bedrock Mantle 3P의 GPT 18채널 TTFB/TTFT 정밀 측정 (v2.18.0).

18채널 = Mantle 인리전 11 + CRIS 7 (GPT 6 Sol/Luna 편입 v2.28.0, 2026-09-23 사용자 결정).

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
import socket
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

RUNS_PER_CHANNEL = int(os.environ.get("GPT_BENCH_RUNS", "10"))
# 호출 1회의 wall-clock 상한 (v2.28.0부터 진짜 상한) — httpx timeout(청크 간 read 대기 상한)과
# _CallWatchdog(호출 전체 경과 상한) 양쪽에 같은 값을 쓴다.
CALL_TIMEOUT_S = float(os.environ.get("GPT_BENCH_CALL_TIMEOUT", "90"))
# 사이클 전체 데드라인 — 15분 스케줄 겹침 방지 (초과 시 남은 채널 skip).
CYCLE_DEADLINE_S = float(os.environ.get("GPT_BENCH_DEADLINE", "780"))  # 13 min

INSTRUCTIONS = "You are a precise technical assistant. Answer in one short sentence."

# (family, model-id env var, 제공 리전) — prober._OPENAI_MODEL_SPECS의 3P(Mantle) 서브셋.
# 18채널 = Mantle 인리전 11 + CRIS 7 (v2.28.0).
# GPT 5.6 Sol/Luna는 대상 아님 (사용자 지정: 5.4 / 5.5 / 5.6 Terra / 6 Astra / 6 Sol / 6 Luna).
# pseudo-region "global" = Global CRIS 채널 (Terra v2.20.1, 2026-08-18 사용자 승인) —
# 5.4/5.5는 global 프로파일 미지원. pseudo-region "us" = US CRIS (GPT 6 세대 전용 — Astra v2.25.1,
# Sol/Luna v2.28.0). pseudo-region 채널의 모델 id/라벨은 prober 규약(_OPENAI_PSEUDO_REGIONS)으로 파생한다.
# GPT 6 Astra는 v2.25.1(2026-09-11) 사용자 결정으로 편입 — Mantle 인리전은 us-west-2 단독.
# us-east-1/us-east-2는 현재 미지원(404, 2026-09-09·09-23 실측) — 2026-09-23 사용자 결정으로 제외,
# 정기 재확인 대상 아님.
# GPT 6 Sol/Luna는 v2.28.0(2026-09-23) 사용자 결정으로 편입 — Mantle 인리전은 us-east-1 단독
# (us-east-2/us-west-2는 404, 2026-09-23 실측). 목록 **끝**에 두는 이유: 사이클이 데드라인에
# 걸리면 뒤쪽 채널부터 skip되므로, 컷이 신규 채널에 떨어져 기존 12채널 시계열이 끊기지 않는다.
_BENCH_SPECS: list[tuple[str, str, tuple[str, ...]]] = [
    ("GPT 5.4", "BEDROCK_OPENAI_GPT_54_MODEL_ID", ("us-east-1", "us-east-2", "us-west-2")),
    ("GPT 5.5", "BEDROCK_OPENAI_GPT_55_MODEL_ID", ("us-east-1", "us-east-2")),
    ("GPT 5.6 Terra", "BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID", ("global", "us-east-1", "us-east-2", "us-west-2")),
    ("GPT 6 Astra", "BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID", ("global", "us", "us-west-2")),
    ("GPT 6 Sol", "BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID", ("global", "us", "us-east-1")),
    ("GPT 6 Luna", "BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID", ("global", "us", "us-east-1")),
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
            # 측정 호출은 절대 조용히 재시도하지 않는다 — SDK 기본 max_retries=2는 실패를
            # 숨기고 한 호출의 경과를 최대 3배로 늘린다. 실패는 오류 행으로 드러나야 한다.
            max_retries=0,
        )
    return _client_cache[base_url]


def _abort_stream(stream) -> None:
    """watchdog 만료 시 열린 스트림을 즉시 끊는다 (best effort).

    stream.close()만으로는 부족하다: 다른 스레드가 recv()에 블로킹돼 있으면 Linux에서 소켓
    close는 그 recv를 깨우지 않아 read timeout까지 더 기다린다 (2026-09-23 로컬 실험 — close만:
    10s read timeout까지 대기, shutdown 선행: 즉시 ReadError, 평문·TLS 동일). 그래서 httpcore
    network_stream의 소켓을 먼저 shutdown(SHUT_RDWR)해 블로킹 read를 깨운 뒤 close한다.
    """
    try:
        resp = getattr(stream, "response", None)
        ns = resp.extensions.get("network_stream") if resp is not None else None
        sock = ns.get_extra_info("socket") if ns is not None else None
        if sock is not None:
            sock.shutdown(socket.SHUT_RDWR)
    except Exception:  # noqa: BLE001 — 이미 닫힘/소켓 미노출 등은 close로 폴백
        pass
    try:
        stream.close()
    except Exception:  # noqa: BLE001
        pass


class _CallWatchdog:
    """호출 1회의 wall-clock 상한 (CALL_TIMEOUT_S) — v2.28.0 하드닝.

    OpenAI 클라이언트 timeout은 httpx read timeout(청크 간 대기 상한)일 뿐이라, 이벤트가 드문드문
    계속 오면 호출 전체는 끝없이 길어진다 — 2026-09-16~17 GPT 5.4 us-east-2 워밍업 1회가 ~3,540s
    (사이클 3,582s, 태스크 최대 4개 겹침). 타이머는 호출 시작부터 돌고, 만료되면 열린 스트림을
    끊는다. 스트림이 열리기 전(응답 헤더 대기 중)에 만료되면 열리는 즉시 끊는다 — 헤더 대기
    자체는 httpx connect/read timeout이 상한이다. 순차 실행은 그대로다 (별도 워커 스레드 없음).
    """

    def __init__(self, limit_s: float):
        self.limit_s = limit_s
        self.fired = False
        self._stream = None
        self._lock = threading.Lock()
        self._timer = threading.Timer(limit_s, self._fire)
        self._timer.daemon = True

    def start(self) -> None:
        self._timer.start()

    def cancel(self) -> None:
        self._timer.cancel()

    def attach(self, stream) -> None:
        with self._lock:
            self._stream = stream
            fired = self.fired
        if fired:
            _abort_stream(stream)

    def _fire(self) -> None:
        with self._lock:
            self.fired = True
            stream = self._stream
        if stream is not None:
            _abort_stream(stream)


def bench_channels() -> list[dict]:
    """env로 활성화된 (family, region, actual_id) 채널 목록 — Mantle 키 없으면 빈 목록."""
    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY not set - GPT bench skipped")
        return []
    # 리전→env 매핑과 pseudo-region 규약(id 접두사·라벨 서픽스)은 prober가 source of truth —
    # 여기서 재정의하면 gpt_bench_results의 키/라벨이 대시보드 채널과 조용히 드리프트한다.
    # 지연 import는 _client_for와 동일한 이유(모듈 로드 시 등록 부작용 없음).
    from prober import _OPENAI_PSEUDO_REGIONS, _OPENAI_REGION_ENV

    chans = []
    for family, env_var, regions in _BENCH_SPECS:
        actual_id = os.environ.get(env_var)
        if not actual_id:
            continue
        for region in regions:
            env_name = _OPENAI_REGION_ENV.get(region)
            if not env_name or not os.environ.get(env_name):
                # prober와 동일: 미등록 리전(오타/선행 추가)은 채널 하나만 건너뛴다 — KeyError로
                # 15분 사이클 전체가 비는 사고 방지.
                continue
            pseudo = _OPENAI_PSEUDO_REGIONS.get(region)
            if pseudo:
                # CRIS 프로파일 id = 접두사("global."/"us.") + in-region id, 라벨은
                # "(Global)"/"(US)" 대문자 — prober._register_openai_models와 동일 규약.
                prefix, label_suffix = pseudo
                channel_id = f"{prefix}{actual_id}"
                label = f"OpenAI {family} ({label_suffix})"
            else:
                channel_id = actual_id
                label = f"OpenAI {family} ({region})"
            chans.append(dict(
                family=family, region=region, actual_id=channel_id,
                model_id=f"openai:{region}:{channel_id}",
                model_name=label,
            ))
    return chans


def one_call(region: str, actual_id: str) -> dict:
    """단일 스트리밍 호출 — TTFB/TTFT/usage 수집 (벤치 스크립트 one_call과 동일 로직).

    CALL_TIMEOUT_S를 넘긴 호출은 watchdog이 스트림을 끊고 오류("wall-clock timeout after Ns")로
    반환한다 — run_cycle의 기존 오류 행 경로로 저장된다.
    """
    client = _client_for(region)
    t0 = time.perf_counter()
    ttfb = ttft = None
    cached = reasoning = out_tok = in_tok = None
    err = None
    done = False  # 만료 전 종료 이벤트 수신 — 만료와 경합해도 상한 안에 끝난 호출은 오류로 뒤집지 않는다
    watchdog = _CallWatchdog(CALL_TIMEOUT_S)
    watchdog.start()
    try:
        stream = client.responses.create(
            model=actual_id, input=_INPUT, instructions=INSTRUCTIONS,
            max_output_tokens=4096, stream=True, extra_body=_EXTRA,
        )
        watchdog.attach(stream)
        for ev in stream:
            now = time.perf_counter()
            et = getattr(ev, "type", "")
            if ttfb is None:
                ttfb = (now - t0) * 1000.0
            if et == "response.output_text.delta" and ttft is None:
                ttft = (now - t0) * 1000.0
            if et in ("response.completed", "response.incomplete", "response.failed"):
                # 만료 뒤에 (버퍼에 남은) 종료 이벤트가 와도 상한 초과 호출이다.
                done = not watchdog.fired
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
    finally:
        watchdog.cancel()
    if watchdog.fired and not done:
        # 끊긴 스트림의 ReadError 등 부수 예외 대신 원인을 명확히 남긴다.
        err = f"WallClockTimeout: wall-clock timeout after {CALL_TIMEOUT_S:g}s"
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
