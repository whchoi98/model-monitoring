"""공개 조회 엔드포인트의 응답 골든과 스캔 상한 — 2026-09-30 /analysis OOM 회귀 테스트.

사고(2026-09-30 16:01 UTC, v2.32.0, backend 태스크 1024 MiB): /analysis 화면은
/api/analysis/stop-reasons와 /api/analysis/output-length(기본 7d)를 동시에 부른다. 두 요청이 창 안의
probe_results 행을 prompt, output_text까지 담은 ORM 엔티티로 모두 읽어 메모리가 20%에서 57%로 오르고,
두 번째 로드에서 컨테이너가 OOM(exit 137)으로 죽었다.

응답 골든: tests/_read_dataset.py의 SQLite 데이터셋(시각은 FROZEN_NOW 기준으로 고정)에서 v2.32.0(98af18e) 코드가 낸 응답을
tests/fixtures/read_goldens_v2320.json에 고정했다. 조회 방식을 바꾼 뒤에도 키 순서까지 같아야 한다.
응답을 의도적으로 바꾸는 변경이 아니면 골든을 다시 만들지 않는다(다시 만들 때:
FREEZE_READ_GOLDENS=1 python3.12 -m pytest tests/test_read_scan_bounds.py -k freeze).

스캔 상한: SQL 캡처(before_cursor_execute)로 probe_results의 Text 열(prompt, output_text)을 SELECT하지 않는지
확인한다. 분석 두 엔드포인트는 GROUP BY로 센 값만, 신뢰성, 효율성, 비용 추이, 결과 통계는 쓰는 열만 stream_results로
읽는다. 창 상한(분석과 비용 추이 30d, 신뢰성과 효율성 7d)을 넘거나 읽을 수 없는 window는 DB를 읽기 전에 422이고,
결과 통계는 run_id 없이 31일보다 이른 start_time을 31일 전으로 당긴다.
"""

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import window_spec
from database import get_db
from routers import analysis as analysis_router
from routers import cost as cost_router
from routers import efficiency as efficiency_router
from routers import reliability as reliability_router
from routers import results as results_router
from tests._read_dataset import CATALOG, FROZEN_NOW, FrozenDatetime, seed

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "read_goldens_v2320.json"
FREEZE = os.environ.get("FREEZE_READ_GOLDENS") == "1"


def _iso_z(delta: timedelta) -> str:
    return (FROZEN_NOW - delta).strftime("%Y-%m-%dT%H:%M:%SZ")  # "+00:00"의 "+"는 쿼리 문자열에서 공백이 된다


_START_7D = _iso_z(timedelta(days=7))
_START_30D = _iso_z(timedelta(days=30))
_START_48H = _iso_z(timedelta(hours=48))
_END_12H = _iso_z(timedelta(hours=12))
# 이름 → 요청 URL. 창 상한 이하의 요청만 넣는다(상한을 넘는 요청은 바뀐 동작이라 골든이 아니다).
_ANALYSIS_QUERIES = {
    "default": "",
    "24h": "?window=24h",
    "30d": "?window=30d",
    "720h": "?window=720h",
    "6h_reasoning": "?window=6h&category=reasoning",
    "30d_chat_short": "?window=30d&category=chat-short",
    "no_unit": "?window=abc",
    "45m": "?window=45m",
}
CASES = {
    **{f"stop_reasons_{k}": f"/api/analysis/stop-reasons{q}" for k, q in _ANALYSIS_QUERIES.items()},
    **{f"output_length_{k}": f"/api/analysis/output-length{q}" for k, q in _ANALYSIS_QUERIES.items()},
    "reliability_default": "/api/reliability/multi-channel",
    "reliability_6h": "/api/reliability/multi-channel?window=6h",
    "reliability_7d": "/api/reliability/multi-channel?window=7d",
    "reliability_168h": "/api/reliability/multi-channel?window=168h",
    "reliability_90m": "/api/reliability/multi-channel?window=90m",
    "efficiency_default": "/api/efficiency/score",
    "efficiency_6h": "/api/efficiency/score?window=6h",
    "efficiency_7d": "/api/efficiency/score?window=7d",
    "efficiency_7d_reasoning": "/api/efficiency/score?window=7d&category=reasoning",
    "cost_trend_default": "/api/cost/trend",
    "cost_trend_6h": "/api/cost/trend?window=6h",
    "cost_trend_7d": "/api/cost/trend?window=7d",
    "cost_trend_30d": "/api/cost/trend?window=30d",
    "results_stats_default": "/api/results/stats",
    "results_stats_7d": f"/api/results/stats?start_time={_START_7D}",
    "results_stats_30d_code_gen": f"/api/results/stats?start_time={_START_30D}&category=code-gen",
    "results_stats_run_2": "/api/results/stats?run_id=2",
    "results_stats_range": f"/api/results/stats?start_time={_START_48H}&end_time={_END_12H}",
}


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P)")
    seed(factory)

    app = FastAPI()
    for module in (analysis_router, reliability_router, efficiency_router, cost_router, results_router):
        app.include_router(module.router)

    def db_override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    # 라우트를 만든 뒤에 바꾼다 — Query 파라미터 타입(datetime)은 라우트 생성 때 이미 해석됐다.
    for module in (analysis_router, reliability_router, efficiency_router, cost_router, results_router):
        monkeypatch.setattr(module, "datetime", FrozenDatetime)
    monkeypatch.setattr(results_router, "AVAILABLE_MODELS", CATALOG)

    statements: list[tuple[str, dict]] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, dict(context.execution_options)))

    event.listen(engine, "before_cursor_execute", record)
    with TestClient(app) as client:
        yield client, statements
    event.remove(engine, "before_cursor_execute", record)
    engine.dispose()


def _canonical(body) -> str:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def _load_goldens() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


@pytest.mark.skipif(not FREEZE, reason="FREEZE_READ_GOLDENS=1일 때만 골든을 다시 만든다")
def test_freeze_goldens(env):
    client, _ = env
    out = {}
    for name, url in CASES.items():
        resp = client.get(url)
        out[name] = {"url": url, "status": resp.status_code, "body": resp.json()}
    GOLDEN_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def test_golden_cases_cover_every_endpoint_with_rows():
    goldens = _load_goldens()
    assert set(goldens) == set(CASES)
    assert all(g["url"] == CASES[name] and g["status"] == 200 for name, g in goldens.items())
    # 데이터셋이 비지 않았는지 — 창마다 행이 있어야 비교가 의미 있다.
    for name, g in goldens.items():
        body = g["body"]
        items = body.get("rows") or body.get("families") or body.get("models") or body.get("points")
        assert items, name


@pytest.mark.skipif(FREEZE, reason="골든을 다시 만드는 중")
@pytest.mark.parametrize("name", sorted(CASES))
def test_response_matches_frozen_golden(env, name):
    client, _ = env
    golden = _load_goldens()[name]
    resp = client.get(CASES[name])
    assert resp.status_code == golden["status"]
    got = resp.json()
    assert got == golden["body"]
    assert _canonical(got) == _canonical(golden["body"])  # dict 키 순서까지


# ───────────────────────────────────────────────────────────────────────
# 스캔 상한 — SELECT 열과 창 상한
# ───────────────────────────────────────────────────────────────────────

ANALYSIS_PATHS = ("/api/analysis/stop-reasons", "/api/analysis/output-length")
STREAMED_PATHS = ("/api/reliability/multi-channel", "/api/efficiency/score", "/api/cost/trend", "/api/results/stats")
_TEXT_COLUMNS = ("probe_results.prompt", "probe_results.output_text")
_OVER_30D = ["31d", "3650d", "99999h", "721h", "43201m"]
_OVER_7D = ["8d", "3650d", "99999h", "169h", "10081m"]
# 경로 → (상한 표기, 상한을 넘는 창, 상한 이하의 창). 상한 = 그 화면이 고를 수 있는 가장 긴 창.
WINDOW_CAPS = {
    "/api/analysis/stop-reasons": ("30d", _OVER_30D, ["30d", "720h", "43200m", "30D", " 7d "]),
    "/api/analysis/output-length": ("30d", _OVER_30D, ["30d", "720h", "43200m", "30D", " 7d "]),
    "/api/reliability/multi-channel": ("7d", _OVER_7D, ["7d", "168h", "10080m", "7D", " 24h "]),
    "/api/efficiency/score": ("7d", _OVER_7D, ["7d", "168h", "10080m", "7D", " 24h "]),
    "/api/cost/trend": ("30d", _OVER_30D, ["30d", "720h", "43200m", "30D", " 7d "]),
}
UNREADABLE_WINDOWS = [
    "xd", "1e3h", "d",
    pytest.param("99999999999d", id="timedelta-overflow"),
    pytest.param("9" * 5000 + "h", id="5000-digit-int"),
]


def _probe_result_selects(statements) -> list[tuple[str, dict]]:
    return [(sql, opts) for sql, opts in statements if "FROM probe_results" in sql]


def _items(body: dict) -> list:
    return body.get("rows") or body.get("families") or body.get("models") or body.get("points") or []


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
@pytest.mark.parametrize("query", ["", "?window=30d&category=reasoning"])
def test_analysis_reads_grouped_counts_not_entities(env, path, query):
    client, statements = env
    statements.clear()
    assert client.get(path + query).status_code == 200
    selects = _probe_result_selects(statements)
    assert len(selects) == 1, selects
    sql = selects[0][0]
    for column in (*_TEXT_COLUMNS, "probe_results.error_message", "probe_results.id AS probe_results_id"):
        assert column not in sql, sql
    assert "GROUP BY" in sql, sql


@pytest.mark.parametrize("path", STREAMED_PATHS)
@pytest.mark.parametrize("query", [{}, {"window": "7d", "start_time": _START_7D}])
def test_streamed_endpoints_read_only_metric_columns_in_batches(env, path, query):
    client, statements = env
    statements.clear()
    assert client.get(path, params=query).status_code == 200  # 쓰지 않는 파라미터는 무시된다
    selects = _probe_result_selects(statements)
    assert len(selects) == 1, selects
    sql, opts = selects[0]
    for column in (*_TEXT_COLUMNS, "probe_results.error_message AS", "probe_results.id AS probe_results_id"):
        assert column not in sql, sql
    assert opts.get("stream_results") is True and opts.get("yield_per"), opts  # PostgreSQL 서버 측 커서


def test_reliability_reads_error_message_only_for_failed_rows(env):
    client, statements = env
    statements.clear()
    assert client.get("/api/reliability/multi-channel?window=7d").status_code == 200
    (sql, _), = _probe_result_selects(statements)
    assert "CASE WHEN (probe_results.status != ?) THEN probe_results.error_message END" in sql, sql


@pytest.mark.parametrize(("path", "window"), [(p, w) for p, (_, over, _) in WINDOW_CAPS.items() for w in over])
def test_window_over_the_cap_is_rejected_before_any_scan(env, path, window):
    client, statements = env
    statements.clear()
    resp = client.get(path, params={"window": window})
    assert resp.status_code == 422
    assert f"최대 {WINDOW_CAPS[path][0]}" in resp.json()["detail"]
    assert _probe_result_selects(statements) == []


@pytest.mark.parametrize("path", list(WINDOW_CAPS))
@pytest.mark.parametrize("window", UNREADABLE_WINDOWS)
def test_unreadable_window_is_422_not_500(env, path, window):
    client, statements = env
    statements.clear()
    resp = client.get(path, params={"window": window})
    assert resp.status_code == 422
    assert "window" in resp.json()["detail"]
    assert _probe_result_selects(statements) == []


@pytest.mark.parametrize(("path", "window"), [(p, w) for p, (_, _, ok) in WINDOW_CAPS.items() for w in ok])
def test_window_up_to_the_cap_is_accepted(env, path, window):
    client, _ = env
    resp = client.get(path, params={"window": window})
    assert resp.status_code == 200
    assert resp.json()["window"] == window  # 요청 문자열을 그대로 돌려준다
    assert _items(resp.json())


@pytest.mark.parametrize("path", ["/api/cost/summary", "/api/cost/channel-compare"])
def test_cost_summary_and_channel_compare_stay_uncapped_but_reject_unreadable_windows(env, path):
    """SQL 집계(모델별 행)라 메모리가 창 길이와 무관하다 — 상한 없이 예전처럼 받고, 읽을 수 없는 값만 500 대신 422."""
    client, _ = env
    assert client.get(path, params={"window": "3650d"}).status_code == 200
    assert client.get(path, params={"window": "1e3h"}).status_code == 422


def _stats(client, **params) -> dict:
    resp = client.get("/api/results/stats", params=params)
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.parametrize("start_time", ["1970-01-01T00:00:00Z", "1970-01-01T00:00:00", _iso_z(timedelta(days=45))])
def test_results_stats_start_time_older_than_31_days_is_clamped(env, caplog, start_time):
    client, _ = env
    floor = _iso_z(timedelta(days=31))
    with caplog.at_level("WARNING", logger="routers.results"):
        body = _stats(client, start_time=start_time)
    assert body["start_time"] == floor  # 실제로 읽은 하한을 돌려준다
    assert body["models"] == _stats(client, start_time=floor)["models"]
    assert "older than 31 days" in caplog.text
    # 데이터셋에 31일보다 오래된 success 행(960h)이 있어야 당김이 의미 있다 — run_id로만 거르면 그 행까지 센다.
    old_rows = {m["model_id"]: m["count"] for m in _stats(client, run_id=1, start_time="1970-01-01T00:00:00Z")["models"]}
    assert sum(old_rows.values()) > sum(m["count"] for m in body["models"])


@pytest.mark.parametrize("delta", [timedelta(days=30), timedelta(days=30, hours=23)])
def test_results_stats_start_time_within_31_days_is_kept(env, delta):
    client, _ = env
    start_time = _iso_z(delta)
    assert _stats(client, start_time=start_time)["start_time"] == start_time


def test_results_stats_with_run_id_keeps_an_old_start_time(env):
    """run_id가 있으면 그 run 하나로 한정되므로 start_time을 당기지 않는다."""
    client, _ = env
    body = _stats(client, run_id=1, start_time="1970-01-01T00:00:00Z")
    assert body["start_time"] == "1970-01-01T00:00:00Z"
    assert body["models"]


def test_parse_window_keeps_the_no_unit_fallback_and_accepts_any_size_without_a_cap():
    assert window_spec.parse_window("") == timedelta(hours=24)
    assert window_spec.parse_window("abc") == timedelta(hours=24)  # 단위가 없으면 예전처럼 24h
    assert window_spec.parse_window("7") == timedelta(hours=24)
    assert window_spec.parse_window(" 7D ") == timedelta(days=7)
    assert window_spec.parse_window("45m") == timedelta(minutes=45)
    assert window_spec.parse_window("3650d") == timedelta(days=3650)  # 상한 없는 호출(cost summary)
    cap = timedelta(days=30)
    assert window_spec.parse_window("30d", max_window=cap) == cap
    with pytest.raises(HTTPException) as exc:
        window_spec.parse_window("31d", max_window=cap)
    assert exc.value.status_code == 422
