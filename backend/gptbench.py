"""GPT on AWS 벤치 사이클 — Bedrock Mantle 3P의 GPT 21채널 TTFB/TTFT 정밀 측정 (v2.18.0).

21채널 = Mantle 인리전 12 + CRIS 9 (GPT 6 Sol/Luna 편입 v2.28.0, GPT 6.1 Sol 편입 v2.32.0 — 2026-09-30 사용자 요청).

docs/benchmarks/ttft_bench_n20.py 방법론을 상시 스케줄화한 것:
  TTFB = 요청→첫 스트림 이벤트, TTFT = 요청→첫 output_text.delta, GAP = TTFT−TTFB ≈ thinking.
  ~55.8k 토큰 고정 프롬프트(prompt cache 유도), 채널당 워밍업 1 + RUNS회 **순차** 호출.

두 갈래 병렬 (v2.32.0, 2026-09-30 사용자 결정): 채널을 호스트별 두 갈래로 나눠 동시에 돈다.
  - cris   = 유사 리전 global/us 채널 (bedrock-runtime OpenAI 호환 호스트)
  - mantle = 인리전 채널 (bedrock-mantle.<region> 호스트)
  갈래 **안**은 지금처럼 채널 하나씩 순차다(갈래 안 병렬화 금지 — 같은 호스트 호출이 겹치면 contention이
  레이턴시를 왜곡, 벤치 방법론과 동일 이유). 두 갈래는 호스트가 달라 서로의 대기열에 끼지 않는다.
  사이클 데드라인(CYCLE_DEADLINE_S)은 두 갈래가 공유하는 같은 시각이고, 넘긴 갈래는 자기 남은 채널만
  건너뛴다. DB는 메인 스레드만 만진다 — 갈래는 측정을 run 단위로 큐에 넘기고, 메인이 채널 단위로 커밋한다.
  배경: 18채널 순차 24시간 실측(96사이클) 중앙값 623초, p90 750초, 최대 790초, 9사이클이 끝 채널을 건너뜀.

auto_prober와 분리된 이유: 측정 지표가 다름(TTFB/GAP은 프로브에 없음) + 고정 대형 프롬프트
비용 프로파일이 달라 독립 테이블(gpt_bench_results)/스케줄(rate 15 min)로 운영.

EventBridge Scheduler가 15분마다 gptbench_runner --once 로 기동 (NOT daemon).
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

# 호출당 wall-clock watchdog — v2.28.2에서 prober와 공용 모듈로 옮겼다(동작 동일). 기존 이름을 그대로
# 두는 이유: one_call이 모듈 전역 `_CallWatchdog`을 참조하고 테스트가 이 이름을 monkeypatch한다.
from stream_watchdog import CallWatchdog as _CallWatchdog
from stream_watchdog import abort_stream as _abort_stream  # noqa: F401 — 테스트/호환용 재노출

logger = logging.getLogger(__name__)

RUNS_PER_CHANNEL = int(os.environ.get("GPT_BENCH_RUNS", "10"))
# 호출 1회의 wall-clock 상한 (v2.28.0부터 진짜 상한) — httpx timeout(청크 간 read 대기 상한)과
# _CallWatchdog(호출 전체 경과 상한) 양쪽에 같은 값을 쓴다.
CALL_TIMEOUT_S = float(os.environ.get("GPT_BENCH_CALL_TIMEOUT", "90"))
# 사이클 전체 데드라인 — 15분 스케줄 겹침 방지 (초과 시 그 갈래의 남은 채널 skip). 두 갈래가 공유한다.
CYCLE_DEADLINE_S = float(os.environ.get("GPT_BENCH_DEADLINE", "780"))  # 13 min

# 두 갈래 — 이름은 로그에 그대로 찍힌다.
LANE_CRIS = "cris"
LANE_MANTLE = "mantle"
LANES = (LANE_CRIS, LANE_MANTLE)
# 갈래 대기 여유 — 마지막으로 통과한 데드라인 판정 뒤에는 호출 1회가 더 돈다. watchdog은 스트림이 붙은 뒤에만
# 끊을 수 있어 스트림 전 구간(연결, 본문 쓰기, 응답 헤더 대기)은 클라이언트 connect/write/read timeout이 상한이고,
# 그래서 그 호출은 CALL_TIMEOUT_S를 넘길 수 있다. 이 여유는 최선의 상한일 뿐 보장이 아니다.
# 데드라인 + 호출 상한 + 여유(기본 885초)는 15분(900초) 스케줄보다 작게 유지한다. 이 시각이 지나도 끝나지 않은
# 갈래는 기다리지 않는다 — 큐에 도착한 진행은 모두 저장하고, 진행 중 채널은 끝난 run을 저장해 "라벨 (run N+)",
# 시작하지 못한 채널은 라벨로 보고한다. 사이클이 영영 끝나지 않는 사고 방지.
LANE_JOIN_GRACE_S = 15.0
# 데드라인 판정 시계 — 테스트가 갈래별 가상 시계로 바꾼다.
_clock = time.perf_counter

INSTRUCTIONS = "You are a precise technical assistant. Answer in one short sentence."

# (family, model-id env var, 제공 리전) — prober._OPENAI_MODEL_SPECS의 3P(Mantle) 서브셋.
# 21채널 = Mantle 인리전 12 + CRIS 9 (v2.32.0).
# GPT 5.6 Sol/Luna는 대상 아님 (사용자 지정: 5.4 / 5.5 / 5.6 Terra / 6 Astra / 6 Sol / 6 Luna / 6.1 Sol).
# pseudo-region "global" = Global CRIS 채널 (Terra v2.20.1, 2026-08-18 사용자 승인) —
# 5.4/5.5는 global 프로파일 미지원. pseudo-region "us" = US CRIS (GPT 6 세대 전용 — Astra v2.25.1,
# Sol/Luna v2.28.0). pseudo-region 채널의 모델 id/라벨은 prober 규약(_OPENAI_PSEUDO_REGIONS)으로 파생한다.
# GPT 6 Astra는 v2.25.1(2026-09-11) 사용자 결정으로 편입 — Mantle 인리전은 us-west-2 단독.
# us-east-1/us-east-2는 현재 미지원(404, 2026-09-09·09-23 실측) — 2026-09-23 사용자 결정으로 제외,
# 정기 재확인 대상 아님.
# GPT 6 Sol/Luna는 v2.28.0(2026-09-23) 사용자 결정으로 편입 — Mantle 인리전은 us-east-1 단독
# (us-east-2/us-west-2는 현재 미지원(404) — 2026-09-23 사용자 결정으로 제외, 정기 재확인 대상 아님). 목록 **끝**에 두는 이유: 사이클이 데드라인에
# 걸리면 뒤쪽 채널부터 skip되므로, 컷이 신규 채널에 떨어져 기존 채널 시계열이 끊기지 않는다.
# GPT 6.1 Sol(v2.32.0): Global CRIS(Seoul bedrock-runtime 200), US CRIS(us-east-1 bedrock-runtime 200), Mantle us-east-1(구독 개시 401 후 200).
# us-east-2/us-west-2는 404로 제외. 목록 끝 = 두 갈래(CRIS, Mantle) 각각의 끝 — 데드라인 컷이 갈래마다 6.1 Sol부터
# 떨어져 기존 18채널 시계열을 보존한다(v2.32.0부터 갈래 순서는 이 목록 순서를 갈래별로 거른 것).
_BENCH_SPECS: list[tuple[str, str, tuple[str, ...]]] = [
    ("GPT 5.4", "BEDROCK_OPENAI_GPT_54_MODEL_ID", ("us-east-1", "us-east-2", "us-west-2")),
    ("GPT 5.5", "BEDROCK_OPENAI_GPT_55_MODEL_ID", ("us-east-1", "us-east-2")),
    ("GPT 5.6 Terra", "BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID", ("global", "us-east-1", "us-east-2", "us-west-2")),
    ("GPT 6 Astra", "BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID", ("global", "us", "us-west-2")),
    ("GPT 6 Sol", "BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID", ("global", "us", "us-east-1")),
    ("GPT 6 Luna", "BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID", ("global", "us", "us-east-1")),
    ("GPT 6.1 Sol", "BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID", ("global", "us", "us-east-1")),
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
_client_lock = threading.Lock()  # 두 갈래 스레드가 캐시를 함께 쓴다


def _client_for(region: str):
    """리전별 Mantle OpenAI 클라이언트 (prober와 동일한 env 규약)."""
    from prober import _openai_base_url  # 지연 import — 등록 부작용 없음

    base_url = _openai_base_url(region)
    with _client_lock:
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


def lane_of(channel: dict) -> str:
    """채널의 갈래 — 유사 리전(global/us, bedrock-runtime 호스트)이면 CRIS, 인리전(bedrock-mantle)이면 Mantle."""
    from prober import _OPENAI_PSEUDO_REGIONS  # 지연 import — bench_channels와 같은 이유

    return LANE_CRIS if channel["region"] in _OPENAI_PSEUDO_REGIONS else LANE_MANTLE


def bench_lanes(chans: list[dict]) -> dict[str, list[tuple[int, dict]]]:
    """갈래별 (bench_channels 위치, 채널) 목록 — 갈래 안 순서는 bench_channels 순서, 빈 갈래는 빠진다."""
    lanes: dict[str, list[tuple[int, dict]]] = {lane: [] for lane in LANES}
    for index, ch in enumerate(chans):
        lanes[lane_of(ch)].append((index, ch))
    return {lane: items for lane, items in lanes.items() if items}


def one_call(region: str, actual_id: str) -> dict:
    """단일 스트리밍 호출 — TTFB/TTFT/usage 수집 (벤치 스크립트 one_call과 동일 로직).

    CALL_TIMEOUT_S 안에 종료 이벤트를 받지 못한 호출은 watchdog이 스트림을 끊고 오류("wall-clock
    timeout after Ns")로 반환한다 — run_cycle의 기존 오류 행 경로로 저장된다. 종료 이벤트를 상한 안에
    받은 호출은 그 뒤 만료된 watchdog의 abort 예외가 나도 측정을 그대로 남긴다.
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
        # 상한 안에 종료 이벤트를 받은 뒤(done) 만료된 watchdog이 스트림 꼬리([DONE]/연결 종료)
        # 대기를 끊으면 그 abort가 ReadError 등을 던진다 — 측정은 이미 끝났으므로 오류 행으로
        # 뒤집지 않는다. fired는 abort 전에 lock 아래에서 켜지므로 abort가 던진 예외면 항상 True다.
        if not (done and watchdog.fired):
            err = f"{type(e).__name__}: {str(e)[:300]}"
    finally:
        watchdog.cancel()
    if watchdog.fired and not done:
        # 끊긴 스트림의 ReadError 등 부수 예외 대신 원인을 명확히 남긴다.
        err = f"WallClockTimeout: wall-clock timeout after {CALL_TIMEOUT_S:g}s"
    return dict(ttfb_ms=ttfb, ttft_ms=ttft, cached_tokens=cached,
                reasoning_tokens=reasoning, output_tokens=out_tok,
                input_tokens=in_tok, error=err)


@dataclass
class _LaneEvent:
    """갈래 → 메인 스레드 메시지. 진행을 run 단위로 넘긴다 — 갈래가 채널 도중에 멈춰도 끝난 run은 메인에 있다.

    kind: "start" = index 채널 측정 시작(데드라인 판정 통과, 워밍업 직전), "run" = 그 채널의 run 하나 끝남,
    "done" = 채널 끝, "exit" = 갈래 끝(error는 갈래를 멈춘 예외).
    """
    lane: str
    kind: str
    index: int | None = None               # bench_channels 순서의 위치
    run: tuple[int, datetime, dict] | None = None  # "run": (run_no, 완료 시각, one_call 결과)
    skip: str | None = None                # "done": skipped_channels 표기 — 채널 전체면 라벨, 도중이면 "라벨 (run N+)"
    error: BaseException | None = None


def _past_deadline(started: float) -> bool:
    return _clock() - started > CYCLE_DEADLINE_S


def _bench_channel(ch: dict, started: float, emit: Callable[..., None]) -> str | None:
    """채널 하나 = 워밍업 1 + RUNS_PER_CHANNEL회 순차 호출. 반환: skip 표기 또는 None.

    진행은 emit으로 넘긴다 — emit("start")는 워밍업 직전, emit("run", (run_no, 완료 시각, 결과))는 run이 끝날 때마다.
    """
    if _past_deadline(started):
        return ch["model_name"]
    emit("start")
    # 워밍업 1회 (connection/TLS, 캐시 안정화) — 저장하지 않음, 벤치 방법론 동일.
    one_call(ch["region"], ch["actual_id"])
    for run_no in range(1, RUNS_PER_CHANNEL + 1):
        if _past_deadline(started):
            return f"{ch['model_name']} (run {run_no}+)"
        r = one_call(ch["region"], ch["actual_id"])
        emit("run", (run_no, datetime.now(timezone.utc), r))
    return None


def _run_lane(lane: str, items: list[tuple[int, dict]], started: float, out: queue.Queue) -> None:
    """갈래 스레드 — 채널을 순서대로 측정하며 진행을 run 단위로 큐에 넘긴다. DB는 만지지 않는다."""
    error: BaseException | None = None
    try:
        for index, ch in items:
            def emit(kind: str, run: tuple[int, datetime, dict] | None = None, index: int = index) -> None:
                out.put(_LaneEvent(lane=lane, kind=kind, index=index, run=run))

            skip = _bench_channel(ch, started, emit)
            out.put(_LaneEvent(lane=lane, kind="done", index=index, skip=skip))
    except BaseException as e:  # noqa: BLE001 — 메인 스레드가 다른 갈래를 마친 뒤 다시 던진다
        error = e
    finally:
        logger.info("GPT bench lane done: %s channels=%d elapsed=%.0fs", lane, len(items), _clock() - started)
        out.put(_LaneEvent(lane=lane, kind="exit", error=error))


def run_cycle() -> dict:
    """1 사이클 = 활성 채널 × RUNS_PER_CHANNEL, 두 갈래(CRIS, Mantle) 병렬 → gpt_bench_results 저장.

    반환: {"cycle_ts", "channels", "rows", "errors", "skipped_channels"} — skipped_channels는 채널 순서.
    갈래가 예기치 않은 예외로 멈추면 다른 갈래를 끝까지 저장하고 사이클 로그를 남긴 뒤 그 예외를 다시 던진다.
    멈춘 갈래(예외, 대기 상한)의 진행 중 채널은 끝난 run까지 저장하고 "라벨 (run N+)"로 보고한다.
    run을 모두 끝내고 "done"만 못 보낸 채널은 끝난 채널이다(skip 아님).
    """
    from database import SessionLocal
    from models import GptBenchResult

    cycle_ts = datetime.now(timezone.utc)
    started = _clock()
    chans = bench_channels()
    logger.info("GPT bench cycle start: %d channels x %d runs", len(chans), RUNS_PER_CHANNEL)

    lanes = bench_lanes(chans)
    logger.info("GPT bench lanes: %s", " ".join(f"{lane}={len(items)}" for lane, items in lanes.items()) or "none")

    rows = errors = 0
    skipped_at: dict[int, str] = {}
    pending = {lane: {i for i, _ in items} for lane, items in lanes.items()}  # 아직 보고되지 않은 채널
    inflight: dict[str, tuple[int, list[tuple[int, datetime, dict]]]] = {}  # 갈래별 진행 중 채널과 그 채널의 끝난 run
    lane_error: BaseException | None = None
    events: queue.Queue = queue.Queue()
    for lane, items in lanes.items():
        # daemon — 대기 상한을 넘긴(정지한) 갈래가 러너 프로세스 종료를 붙잡지 않도록.
        threading.Thread(target=_run_lane, args=(lane, items, started, events),
                         name=f"gptbench-{lane}", daemon=True).start()
    wait_cap = CYCLE_DEADLINE_S + CALL_TIMEOUT_S + LANE_JOIN_GRACE_S
    db = SessionLocal()

    def store(index: int, runs: list[tuple[int, datetime, dict]]) -> None:
        nonlocal rows, errors
        ch = chans[index]
        for run_no, finished_at, r in runs:
            gap = (r["ttft_ms"] - r["ttfb_ms"]) if (r["ttft_ms"] and r["ttfb_ms"]) else None
            db.add(GptBenchResult(
                cycle_ts=cycle_ts,
                timestamp=finished_at,
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

    def stop_lane(lane: str) -> None:
        """멈춘 갈래의 남은 채널 보고 — 진행 중 채널은 끝난 run을 저장하고 "라벨 (run N+)", 시작 못 한 채널은 라벨.

        진행 중 채널이 run을 RUNS_PER_CHANNEL개 모두 끝냈으면 "done"만 오지 않은 것이다 — "done"을 받은 것과 같이
        처리한다(저장, skip 아님).
        """
        if lane in inflight and len(inflight[lane][1]) >= RUNS_PER_CHANNEL:
            handle(_LaneEvent(lane=lane, kind="done", index=inflight[lane][0]))
        left = pending.pop(lane, set())
        if lane in inflight:
            index, runs = inflight.pop(lane)
            left.discard(index)
            store(index, runs)
            skipped_at[index] = f"{chans[index]['model_name']} (run {len(runs) + 1}+)"
        for i in left:
            skipped_at[i] = chans[i]["model_name"]

    def handle(ev: _LaneEvent) -> None:
        nonlocal lane_error
        if ev.kind == "start":
            inflight[ev.lane] = (ev.index, [])
        elif ev.kind == "run":
            inflight[ev.lane][1].append(ev.run)
        elif ev.kind == "done":
            _, runs = inflight.pop(ev.lane, (ev.index, []))
            pending.get(ev.lane, set()).discard(ev.index)
            ch = chans[ev.index]
            if ev.skip is not None:
                skipped_at[ev.index] = ev.skip
            if not runs and ev.skip == ch["model_name"]:
                logger.warning("cycle deadline exceeded - skipping %s", ch["model_name"])
                return
            store(ev.index, runs)
            logger.info("channel done: %s", ch["model_name"])
        else:  # "exit" — 정상 종료면 남은 채널이 없다. 예외로 멈춘 갈래는 진행 중 채널과 못 돈 채널을 보고한다.
            stop_lane(ev.lane)
            if ev.error is not None:
                logger.error("GPT bench lane %s stopped: %s: %s", ev.lane, type(ev.error).__name__, ev.error,
                             exc_info=ev.error)
                lane_error = lane_error or ev.error

    try:
        while pending:
            remaining = wait_cap - (_clock() - started)
            try:
                # 대기 상한이 지나면 더 기다리지 않고, 이미 큐에 도착한 진행만 비울 때까지 평소처럼 처리한다
                # (메인이 DB 지연 등으로 늦어 쌓인 채널도 저장된다).
                ev = events.get(timeout=min(remaining, 5.0)) if remaining > 0 else events.get_nowait()
            except queue.Empty:
                if remaining > 0:
                    continue
                for lane in list(pending):
                    logger.error("GPT bench lane %s did not finish within %.0fs - abandoning %d channel(s)",
                                 lane, wait_cap, len(pending[lane]))
                    stop_lane(lane)
                break
            handle(ev)
    finally:
        db.close()

    skipped = [skipped_at[i] for i in sorted(skipped_at)]
    elapsed = _clock() - started
    logger.info("GPT bench cycle done: rows=%d errors=%d skipped=%s elapsed=%.0fs",
                rows, errors, skipped or "none", elapsed)
    if lane_error is not None:
        raise lane_error
    return dict(cycle_ts=cycle_ts.isoformat(), channels=len(chans),
                rows=rows, errors=errors, skipped_channels=skipped)
