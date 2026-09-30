"""인사이트 통계 수집의 스캔 상한 — 2026-09-30 /analysis OOM 후속.

POST /api/insights/regenerate와 /api/insights/stream-regenerate(JWT)는 backend 프로세스 안에서
insights_runner.run_once, collect_stats_for_window를 돌린다(backend 태스크 1024 MiB). 예전에는 요청 body의 window에
상한이 없었고(예: "3650d"), 두 함수가 ProbeResult를 prompt, output_text까지 담은 ORM 엔티티로 .all() 적재했다.
run_once는 ProbeRun 엔티티도 읽었는데 ProbeRun.results가 lazy="selectin"이라 그 run들의 ProbeResult가 엔티티로
한 번 더 딸려 왔다.

고정하는 것:
- SQL 캡처(before_cursor_execute): 세 경로(collect_stats_for_window, run_once, stream-regenerate)가 probe_results에서
  compute_stats가 쓰는 다섯 열(model_name, status, ttft_ms, total_latency_ms, tps)만 stream_results로 읽는다.
  probe_results.prompt, output_text, error_message와 probe_runs.prompt는 SELECT하지 않는다.
- 같은 출력: tests/_read_dataset.py 데이터셋에서 _build_prompt가 만드는 프롬프트(KO, EN), run_once가 Bedrock에 보내는
  프롬프트와 저장하는 model_breakdown, stream-regenerate가 보내는 프롬프트가 v2.32.0(엔티티 조회) 코드의 결과와
  바이트 단위로 같다. 골든은 fixtures/insights_prompts_v2320.json이고 바꾸기 전 코드로 만들었다(다시 만들 때:
  FREEZE_INSIGHTS_GOLDENS=1 python3.12 -m pytest tests/test_insights_scan_bounds.py -k freeze).
- API 창 상한: body window는 최대 24h다(인사이트 패널은 6h를 보낸다). 넘거나, 0 이하이거나, 읽을 수 없으면 422이고
  스레드, 스트림, DB 조회를 시작하지 않는다. 스케줄 태스크의 CLI(python -m insights_runner --window 6h)에는 상한이 없다.
"""

import json
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import agent.bedrock
import database
import insights_runner
import models
import streamed_read
from auth import get_current_user
from routers import insights as insights_router
from streamed_read import StreamedReadTimeout
from tests._read_dataset import FrozenDatetime, seed

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "insights_prompts_v2320.json"
FREEZE = os.environ.get("FREEZE_INSIGHTS_GOLDENS") == "1"

PROMPT_CASES = [(window, lang) for window in ("6h", "24h", "3d") for lang in ("ko", "en")]
RUN_ONCE_WINDOW = "6h"  # 스케줄 태스크의 --window
_FORBIDDEN = ("probe_results.prompt", "probe_results.output_text", "probe_results.error_message",
              "probe_results.id AS probe_results_id", "probe_runs.prompt")
_STATS_COLUMNS = ("probe_results.model_name", "probe_results.status", "probe_results.ttft_ms",
                  "probe_results.total_latency_ms", "probe_results.tps")


@pytest.fixture()
def db_env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P)")
    seed(factory)
    monkeypatch.setattr(insights_runner, "datetime", FrozenDatetime)
    monkeypatch.setattr(insights_runner, "SessionLocal", factory)
    monkeypatch.setattr(insights_router, "SessionLocal", factory)

    statements: list[tuple[str, dict]] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, dict(context.execution_options)))

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield factory, statements
    finally:
        event.remove(engine, "before_cursor_execute", record)
        engine.dispose()


@pytest.fixture()
def bedrock_calls(monkeypatch):
    """converse_blocking, converse_stream_text 대역 — 보낸 (system, user 텍스트)를 모은다."""
    calls: list[dict] = []

    def blocking(messages, *, model_id, system=None, max_tokens=2048, temperature=0.1):
        calls.append({"system": system, "user": messages[0]["content"][0]["text"]})
        return f"summary {len(calls)}"

    def stream(messages, *, model_id, system=None, max_tokens=2048, temperature=0.1):
        calls.append({"system": system, "user": messages[0]["content"][0]["text"]})
        yield "부분 1"
        yield "부분 2"

    monkeypatch.setattr(agent.bedrock, "converse_blocking", blocking)
    monkeypatch.setattr(agent.bedrock, "converse_stream_text", stream)
    return calls


@pytest.fixture()
def api(db_env, monkeypatch):
    app = FastAPI()
    app.include_router(insights_router.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(username="tester")
    monkeypatch.setattr(insights_router, "_is_regenerating", False)
    with TestClient(app) as client:
        yield client


def _prompt_texts(factory, window: str, lang: str) -> dict:
    with factory() as db:
        stats = insights_runner.collect_stats_for_window(db, window)
    system, user = insights_runner._build_prompt(window, stats, lang)
    return {"system": system, "user": user}


def _run_once_outputs(factory, calls: list) -> dict:
    calls.clear()
    insight_id = insights_runner.run_once(RUN_ONCE_WINDOW)
    assert insight_id > 0
    with factory() as db:
        breakdown = db.get(models.Insight, insight_id).model_breakdown
    return {"calls": list(calls), "model_breakdown": breakdown}


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_goldens() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _probe_selects(statements) -> list[tuple[str, dict]]:
    return [(sql, opts) for sql, opts in statements if sql.lstrip().upper().startswith("SELECT")
            and ("FROM probe_results" in sql or "FROM probe_runs" in sql)]


def _assert_stats_columns_only(statements, *, runs_query: bool):
    selects = _probe_selects(statements)
    for sql, _ in selects:
        for column in _FORBIDDEN:
            assert column not in sql, sql
    results = [(sql, opts) for sql, opts in selects if "FROM probe_results" in sql]
    assert len(results) == 1, results  # selectin으로 딸려 오는 두 번째 조회가 없다
    sql, opts = results[0]
    for column in _STATS_COLUMNS:
        assert column in sql, sql
    assert opts.get("stream_results") is True and opts.get("yield_per"), opts  # PostgreSQL 서버 측 커서
    assert len([s for s, _ in selects if "FROM probe_runs" in s]) == (1 if runs_query else 0), selects


# ───────────────────────────────────────────────────────────────────────
# 같은 출력 — v2.32.0 골든
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not FREEZE, reason="FREEZE_INSIGHTS_GOLDENS=1일 때만 골든을 다시 만든다")
def test_freeze_goldens(db_env, bedrock_calls):
    factory, _ = db_env
    out = {
        "build_prompt": {f"{w}:{lang}": _prompt_texts(factory, w, lang) for w, lang in PROMPT_CASES},
        f"run_once_{RUN_ONCE_WINDOW}": _run_once_outputs(factory, bedrock_calls),
    }
    GOLDEN_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def test_goldens_cover_several_models_and_statuses():
    goldens = _load_goldens()
    assert set(goldens["build_prompt"]) == {f"{w}:{lang}" for w, lang in PROMPT_CASES}
    breakdown = goldens[f"run_once_{RUN_ONCE_WINDOW}"]["model_breakdown"]
    assert len(breakdown) >= 8 and all("(1P)" not in name for name in breakdown)
    assert any(m["errors"] for m in breakdown.values()) and any(m["tps"]["n"] for m in breakdown.values())
    assert len(goldens[f"run_once_{RUN_ONCE_WINDOW}"]["calls"]) == 2  # KO, EN


@pytest.mark.skipif(FREEZE, reason="골든을 다시 만드는 중")
@pytest.mark.parametrize(("window", "lang"), PROMPT_CASES)
def test_build_prompt_from_window_stats_matches_v2320(db_env, window, lang):
    factory, _ = db_env
    got = _prompt_texts(factory, window, lang)
    golden = _load_goldens()["build_prompt"][f"{window}:{lang}"]
    assert got["system"] == golden["system"]
    assert got["user"] == golden["user"]  # 통계 JSON의 모델 순서와 키 순서까지


@pytest.mark.skipif(FREEZE, reason="골든을 다시 만드는 중")
def test_run_once_prompts_and_saved_breakdown_match_v2320(db_env, bedrock_calls):
    factory, _ = db_env
    got = _run_once_outputs(factory, bedrock_calls)
    golden = _load_goldens()[f"run_once_{RUN_ONCE_WINDOW}"]
    assert got["calls"] == golden["calls"]
    assert _canonical(got["model_breakdown"]) == _canonical(golden["model_breakdown"])


@pytest.mark.skipif(FREEZE, reason="골든을 다시 만드는 중")
@pytest.mark.parametrize("lang", ["ko", "en"])
def test_stream_regenerate_sends_the_v2320_prompt(api, db_env, bedrock_calls, lang):
    factory, _ = db_env
    resp = api.post("/api/insights/stream-regenerate", json={"window": "6h", "lang": lang})
    assert resp.status_code == 200
    assert "event: final" in resp.text and '"ok": true' in resp.text
    assert bedrock_calls == [_load_goldens()["build_prompt"][f"6h:{lang}"]]
    with factory() as db:
        saved = db.query(models.Insight).one()
    assert saved.summary_md == "부분 1부분 2"


# ───────────────────────────────────────────────────────────────────────
# SQL 캡처 — 쓰는 열만, 나눠 읽기
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("window", ["6h", "24h", "3d"])
def test_collect_stats_reads_only_the_stats_columns_in_batches(db_env, window):
    factory, statements = db_env
    with factory() as db:
        statements.clear()
        assert insights_runner.collect_stats_for_window(db, window)
    _assert_stats_columns_only(statements, runs_query=False)


def test_run_once_reads_run_ids_and_stats_columns_only(db_env, bedrock_calls):
    factory, statements = db_env
    statements.clear()
    assert insights_runner.run_once(RUN_ONCE_WINDOW) > 0
    _assert_stats_columns_only(statements, runs_query=True)


def test_run_once_skips_when_no_auto_run_in_the_window(db_env, bedrock_calls):
    factory, _ = db_env
    with factory() as db:
        db.query(models.ProbeResult).delete()
        db.query(models.ProbeRun).delete()
        db.commit()
    assert insights_runner.run_once(RUN_ONCE_WINDOW) == 0
    assert bedrock_calls == []


def test_run_once_skips_when_every_row_of_the_runs_is_hidden(db_env, bedrock_calls, monkeypatch):
    factory, _ = db_env
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(")  # 모든 라벨에 "("가 있다 — weird-label만 남는다
    with factory() as db:
        db.query(models.ProbeResult).filter(models.ProbeResult.model_name == "weird-label").delete()
        db.commit()
    assert insights_runner.run_once(RUN_ONCE_WINDOW) == 0
    assert bedrock_calls == []


def test_stream_regenerate_reads_only_the_stats_columns(api, db_env, bedrock_calls):
    _, statements = db_env
    statements.clear()
    assert api.post("/api/insights/stream-regenerate", json={"window": "24h"}).status_code == 200
    _assert_stats_columns_only(statements, runs_query=False)


def test_regenerate_thread_reads_only_the_stats_columns(api, db_env, bedrock_calls, monkeypatch):
    _, statements = db_env
    done = threading.Event()
    results: list[int] = []
    real_run_once = insights_runner.run_once

    def run_once(window_spec="6h"):
        try:
            results.append(real_run_once(window_spec))
        finally:
            done.set()

    monkeypatch.setattr(insights_runner, "run_once", run_once)  # _run_regenerate가 부를 때 import한다
    statements.clear()
    resp = api.post("/api/insights/regenerate", json={"window": "24h"})
    assert resp.status_code == 200
    assert resp.json() == {"triggered": True, "message": "인사이트 생성 시작 (window=24h)"}
    assert done.wait(10)
    assert results and results[0] > 0
    _assert_stats_columns_only(statements, runs_query=True)


# ───────────────────────────────────────────────────────────────────────
# API 창 상한 — body window 최대 24h
# ───────────────────────────────────────────────────────────────────────

OVER_24H = ["25h", "2d", "48h", "3650d", "99999999d"]
NON_POSITIVE = ["0h", "0d", "00h"]
# 형식은 insights_runner.parse_window('6h', '1d')를 따른다 — m 단위, 단위 없음, 음수는 읽을 수 없는 값이다.
# timedelta 범위를 넘는 수(30자리 일)와 int 변환 한도를 넘는 수(5000자리)도 window_spec과 같이 읽을 수 없는 값이다.
UNREADABLE = ["45m", "abc", "6", "", "1e3h", "-1h", "6 h", "9" * 30 + "d", "9" * 5000 + "h"]
ACCEPTED = ["6h", "24h", "1d", " 6H "]


_REJECTED_CASES = [
    (path, window, fragment)
    for path in ("/api/insights/regenerate", "/api/insights/stream-regenerate")
    for windows, fragment in ((OVER_24H, "최대 24h"), (NON_POSITIVE, "0보다 길어야"), (UNREADABLE, "읽을 수 없습니다"))
    for window in windows
]


@pytest.mark.parametrize(("path", "window", "fragment"), _REJECTED_CASES,
                         ids=[f"{p.rsplit('/', 1)[1]}-{w!r}" if len(w) <= 12 else f"{p.rsplit('/', 1)[1]}-{len(w)}-chars"
                              for p, w, _ in _REJECTED_CASES])
def test_regenerate_window_over_24h_or_unusable_is_422_before_any_work(api, db_env, bedrock_calls, monkeypatch,
                                                                       path, window, fragment):
    _, statements = db_env
    started: list[str] = []
    monkeypatch.setattr(insights_runner, "run_once", lambda window_spec="6h": started.append(window_spec))
    statements.clear()
    resp = api.post(path, json={"window": window})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, str) and "window" in detail and fragment in detail, detail
    assert started == [] and insights_router._is_regenerating is False  # 스레드를 시작하지 않았다
    assert bedrock_calls == [] and _probe_selects(statements) == []


@pytest.mark.parametrize("window", ACCEPTED)
def test_regenerate_accepts_windows_up_to_24h(api, monkeypatch, window):
    started: list[str] = []
    done = threading.Event()

    def run_once(window_spec="6h"):
        started.append(window_spec)
        done.set()

    monkeypatch.setattr(insights_runner, "run_once", run_once)
    resp = api.post("/api/insights/regenerate", json={"window": window})
    assert resp.status_code == 200
    assert resp.json() == {"triggered": True, "message": f"인사이트 생성 시작 (window={window})"}
    assert done.wait(10) and started == [window]  # body 문자열을 그대로 넘긴다


def test_regenerate_default_body_is_the_6h_window(api, monkeypatch):
    started: list[str] = []
    done = threading.Event()
    monkeypatch.setattr(insights_runner, "run_once", lambda window_spec="6h": (started.append(window_spec), done.set()))
    assert api.post("/api/insights/regenerate", json={}).status_code == 200
    assert done.wait(10) and started == ["6h"]


@pytest.mark.parametrize("window", ["24h", "1d"])
def test_stream_regenerate_accepts_24h_and_saves_its_window(api, db_env, bedrock_calls, window):
    factory, _ = db_env
    resp = api.post("/api/insights/stream-regenerate", json={"window": window})
    assert resp.status_code == 200 and "event: final" in resp.text
    with factory() as db:
        saved = db.query(models.Insight).one()
    assert (saved.window_end - saved.window_start).total_seconds() == 24 * 3600


def test_cli_window_stays_uncapped_for_the_scheduled_task(db_env, bedrock_calls, monkeypatch):
    """스케줄 태스크(--window 6h, 기본값도 6h)와 운영자가 CLI로 돌리는 긴 창은 API 상한과 무관하다."""
    assert insights_runner.run_once("3d") > 0
    started: list[str] = []
    monkeypatch.setattr(insights_runner, "run_once", lambda window_spec="6h": started.append(window_spec) or 1)
    for argv, expected in ((["insights_runner"], "6h"), (["insights_runner", "--window", "3d"], "3d")):
        monkeypatch.setattr(sys, "argv", argv)
        assert insights_runner.main() == 0
        assert started.pop() == expected


# ───────────────────────────────────────────────────────────────────────
# 전체 시간 상한 — streamed_read.stream_rows
# ───────────────────────────────────────────────────────────────────────
# statement_timeout(database.py)은 문장 하나의 상한이라 서버 측 커서(yield_per)에는 FETCH마다 따로 걸린다. 두 통계 조회는
# streamed_read.stream_rows가 같은 상한(database._STATEMENT_TIMEOUT_MS)으로 전체 경과 시간을 재고, 넘으면 커서를 닫고
# StreamedReadTimeout을 던진다(2026-09-30 v2.32.1 통합 리뷰). 기존 호출자가 처리한다: run_once는 except에서 -1(스케줄
# 태스크는 exit 1), stream-regenerate는 error 이벤트, regenerate 스레드는 run_once의 -1 뒤 잠금을 푼다.
# 가짜 시계는 부를 때마다 1초씩 가고 상한은 5초다 — 시작 시각을 한 번 잰 뒤 행마다 재므로 여섯 번째 행에서 멈춘다.


@pytest.fixture()
def slow_clock(monkeypatch):
    ticks = {"now": 0.0, "calls": 0}

    def clock() -> float:
        ticks["calls"] += 1
        ticks["now"] += 1.0
        return ticks["now"]

    monkeypatch.setattr(streamed_read, "_clock", clock)
    monkeypatch.setattr(database, "_STATEMENT_TIMEOUT_MS", 5000)
    return ticks


def test_collect_stats_past_the_statement_timeout_raises_mid_stream(db_env, slow_clock, caplog):
    factory, statements = db_env
    with factory() as db:
        statements.clear()
        with caplog.at_level("WARNING", logger="streamed_read"):
            with pytest.raises(StreamedReadTimeout) as exc:
                insights_runner.collect_stats_for_window(db, "24h")
    assert exc.value.what == "insights_runner.collect_stats_for_window window='24h'"
    assert exc.value.rows == 5 and slow_clock["calls"] == 7  # 시작 1 + 행 6 — 창 안의 행은 5행보다 훨씬 많다
    assert "insights_runner.collect_stats_for_window window='24h' (elapsed 6.0s, 5 rows)" in caplog.text
    assert len([s for s, _ in _probe_selects(statements) if "FROM probe_results" in s]) == 1


def test_run_once_past_the_statement_timeout_returns_minus_1_before_bedrock(db_env, bedrock_calls, slow_clock, caplog):
    factory, _ = db_env
    with caplog.at_level("WARNING"):
        assert insights_runner.run_once(RUN_ONCE_WINDOW) == -1
    assert bedrock_calls == []
    with factory() as db:
        assert db.query(models.Insight).count() == 0
    assert "insights_runner.run_once window='6h' (elapsed 6.0s, 5 rows)" in caplog.text
    assert "insights_runner 실패" in caplog.text  # run_once의 기존 except가 처리했다


def test_cli_exits_1_when_the_stats_read_times_out(db_env, bedrock_calls, slow_clock, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["insights_runner", "--window", "6h"])
    assert insights_runner.main() == 1
    assert bedrock_calls == []


def test_stream_regenerate_reports_the_timeout_as_one_sse_error_event(api, db_env, bedrock_calls, slow_clock):
    factory, _ = db_env
    resp = api.post("/api/insights/stream-regenerate", json={"window": "6h", "lang": "ko"})
    assert resp.status_code == 200
    blocks = [b for b in resp.text.split("\n\n") if b]
    assert len(blocks) == 1 and blocks[0].startswith("event: error\ndata: "), resp.text
    message = json.loads(blocks[0].split("data: ", 1)[1])["message"]
    assert message == ("DB 조회가 5초 상한을 넘어 중단했습니다: insights_runner.collect_stats_for_window window='6h' "
                       "(6.0초, 5행)")
    assert bedrock_calls == []
    with factory() as db:
        assert db.query(models.Insight).count() == 0


def test_regenerate_thread_times_out_and_releases_the_lock(api, db_env, bedrock_calls, slow_clock, monkeypatch):
    factory, _ = db_env
    done = threading.Event()
    results: list[int] = []
    real_run_once = insights_runner.run_once

    def run_once(window_spec="6h"):
        try:
            results.append(real_run_once(window_spec))
        finally:
            done.set()

    monkeypatch.setattr(insights_runner, "run_once", run_once)
    resp = api.post("/api/insights/regenerate", json={"window": "6h"})
    assert resp.status_code == 200 and resp.json()["triggered"] is True
    assert done.wait(10) and results == [-1]
    deadline = time.monotonic() + 5
    while insights_router._is_regenerating and time.monotonic() < deadline:
        time.sleep(0.01)
    assert insights_router._is_regenerating is False  # 다음 재생성을 받을 수 있다
    assert bedrock_calls == []
    with factory() as db:
        assert db.query(models.Insight).count() == 0
