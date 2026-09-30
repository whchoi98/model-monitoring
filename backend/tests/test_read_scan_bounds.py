"""공개 조회 엔드포인트의 응답 골든과 스캔 상한 — 2026-09-30 /analysis OOM 회귀 테스트.

사고(2026-09-30 16:01 UTC, v2.32.0, backend 태스크 1024 MiB): /analysis 화면은
/api/analysis/stop-reasons와 /api/analysis/output-length(기본 7d)를 동시에 부른다. 두 요청이 창 안의
probe_results 행을 prompt, output_text까지 담은 ORM 엔티티로 모두 읽어 메모리가 20%에서 57%로 오르고,
두 번째 로드에서 컨테이너가 OOM(exit 137)으로 죽었다.

응답 골든: tests/_read_dataset.py의 SQLite 데이터셋(시각은 FROZEN_NOW 기준으로 고정)에서 v2.32.0(98af18e) 코드가 낸 응답을
tests/fixtures/read_goldens_v2320.json에 고정했다. 조회 방식을 바꾼 뒤에도 키 순서까지 같아야 한다.
응답을 의도적으로 바꾸는 변경이 아니면 골든을 다시 만들지 않는다(다시 만들 때:
FREEZE_READ_GOLDENS=1 python3.12 -m pytest tests/test_read_scan_bounds.py -k freeze).

골든 밖 데이터셋: 골든 데이터셋이 가리지 못하는 변이를 따로 잡는다. (1) 지표 값이 모두 있는 실패 행(error, overloaded,
timeout)을 더해도 success만 세는 응답(분석, 비용 추이, 결과 통계)은 골든 그대로다. (2) id 순서와 시각 순서가 어긋나는
데이터셋에서 분석 행의 model_name 동률과 counts, percentages 키는 처음 나온 순서(min(id))를 따르고, 결과 통계 라벨은
가장 최근 시각의 행 중 먼저 본 행의 것이다.

스캔 상한: SQL 캡처(before_cursor_execute)로 probe_results의 Text 열(prompt, output_text)을 SELECT하지 않는지
확인한다. 분석 두 엔드포인트는 GROUP BY로 센 값만, 신뢰성, 효율성, 비용 추이, 결과 통계는 쓰는 열만 stream_results로
읽는다. 창 상한(분석과 비용 추이 30d, 신뢰성과 효율성 7d)을 넘거나 읽을 수 없는 window는 DB를 읽기 전에 422이고,
결과 통계는 run_id 없이 31일보다 이른 start_time을 31일 전으로 당긴다.
"""

import json
import os
from contextlib import contextmanager
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
from tests._read_dataset import CATALOG, FROZEN_NOW, G, OA, TWIN_B, FrozenDatetime, seed

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


@contextmanager
def _serve(monkeypatch, *seeders):
    """seeders를 차례로 넣은 SQLite로 다섯 라우터를 띄운다 → (TestClient, SQL 캡처 목록)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P)")
    for fill in seeders:
        fill(factory)

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
    try:
        with TestClient(app) as client:
            yield client, statements
    finally:
        event.remove(engine, "before_cursor_execute", record)
        engine.dispose()


@pytest.fixture()
def env(monkeypatch):
    with _serve(monkeypatch, seed) as served:
        yield served


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
# 골든 밖 데이터셋 — 골든 데이터셋이 가리지 못하는 변이를 잡는다
# ───────────────────────────────────────────────────────────────────────

# (1) success가 아닌 행에도 지표 값이 모두 있는 데이터셋. 골든 데이터셋의 실패 행은 output_tokens, stop_reason, 지연시간이
# 모두 NULL이라 output-length에서 status == 'success' 조건을 빼도 응답이 같았다(output_tokens IS NOT NULL이 대신 걸렀다).
# 창(45m, 6h, 24h, 48h~12h, 7d, 30d) × 카테고리 × run 격자마다 실패 행을 넣으므로 success만 세는 요청은 모두 이 행을 창 안에 둔다.
NON_SUCCESS_STATUSES = ("error", "overloaded", "timeout")
FAIL_ONLY = ("anthropic:claude-fail-only", "Anthropic Claude Fail Only (US)")  # 실패 행만 있는 모델
_NON_SUCCESS_OFFSETS_H = (0.5, 4, 10, 30, 100, 400)
_NON_SUCCESS_MODELS = (G, OA, TWIN_B, FAIL_ONLY)  # 단가 있는 모델(G, OA, TWIN_B) — 비용 추이도 달라질 수 있다
_SUCCESS_ONLY_CASES = sorted(
    name for name in CASES if name.startswith(("stop_reasons_", "output_length_", "cost_trend_", "results_stats_"))
)


def _seed_non_success(factory) -> None:
    with factory() as db:
        n = 0
        for offset in _NON_SUCCESS_OFFSETS_H:
            for model_id, label in _NON_SUCCESS_MODELS:
                for category in ("chat-short", "reasoning", "code-gen", None):
                    for run_id in (1, 2):
                        db.add(models.ProbeResult(
                            run_id=run_id, model_id=model_id, model_name=label,
                            timestamp=FROZEN_NOW - timedelta(hours=offset), prompt="failed " + "z" * 200,
                            status=NON_SUCCESS_STATUSES[n % 3], ttft_ms=111.1 + n, total_latency_ms=2222.2 + n,
                            server_latency_ms=1800.5, input_tokens=900 + n, output_tokens=(123, 4000, 777)[n % 3] + n,
                            tps=55.5, output_text="partial " + "w" * 100,
                            error_message="WallClockTimeout: probe exceeded 90s wall-clock",
                            category=category, stop_reason=("max_tokens", "tool_use", "end_turn")[n % 3],
                        ))
                        n += 1
        db.commit()


@pytest.fixture()
def non_success_env(monkeypatch):
    with _serve(monkeypatch, seed, _seed_non_success) as served:
        yield served


@pytest.mark.skipif(FREEZE, reason="골든을 다시 만드는 중")
@pytest.mark.parametrize("name", _SUCCESS_ONLY_CASES)
def test_non_success_rows_with_metrics_leave_success_only_responses_unchanged(non_success_env, name):
    client, _ = non_success_env
    resp = client.get(CASES[name])
    assert resp.status_code == 200
    assert _canonical(resp.json()) == _canonical(_load_goldens()[name]["body"])


@pytest.mark.skipif(FREEZE, reason="골든을 다시 만드는 중")
def test_non_success_rows_reach_the_windows_of_the_success_only_cases(non_success_env):
    """위 비교가 헛돌지 않는지 — 상태를 가리지 않는 신뢰성 응답은 90m, 6h, 24h, 7d 모두 실패 행 때문에 달라진다."""
    client, _ = non_success_env
    goldens = _load_goldens()
    for name in ("reliability_90m", "reliability_6h", "reliability_default", "reliability_7d"):
        assert client.get(CASES[name]).json() != goldens[name]["body"], name


# (2) id 순서와 시각 순서가 어긋나는 데이터셋 — 분석 행의 model_name 동률, counts와 percentages 키 순서, 결과 통계의 최신
# 라벨. 분석의 순서 규칙은 "창 안에서 처음 나온 순서 = min(id)"다(v2.32.1 GROUP BY 전환 때 정했다). 골든 데이터셋은 id 순서가
# 시각 순서와 같고 쌍둥이 id의 알파벳 순서도 처음 나온 순서와 같아, min(id) 대신 model_id나 가장 이른 시각으로 정렬해도 골든이
# 그대로였다. 골든과 따로 둔다 — 골든은 v2.32.0 응답이고, 이 순서는 v2.32.0이 DB 행 순서에 맡기던 것을 새로 고정한 것이다.
TWIN_LABEL = "Anthropic Claude Twin 9 (US)"
TIE_ZZ = ("anthropic:zz-twin-9", TWIN_LABEL)  # 먼저 나오지만(min id 1) 알파벳으로는 뒤
TIE_AA = ("anthropic:aa-twin-9", TWIN_LABEL)  # 이 데이터셋에서 가장 이른 시각의 행을 갖지만 id로는 뒤(min id 2)
STATS_TIE = ("mystery.stats-tie", None)  # 카탈로그 밖 — stats 라벨은 가장 최근 시각의 행 중 먼저 본 행의 라벨
# (모델, 몇 시간 전, stop_reason, output_tokens, 행 라벨) — 넣는 순서가 곧 id다.
TIE_ROWS = (
    (TIE_ZZ, 1, "max_tokens", 900, TWIN_LABEL),          # id 1
    (TIE_AA, 10, "end_turn", 100, TWIN_LABEL),           # id 2 — 가장 이른 시각
    (TIE_ZZ, 6, "end_turn", 200, TWIN_LABEL),            # id 3
    (TIE_AA, 0.5, "tool_use", 50, TWIN_LABEL),           # id 4
    (TIE_ZZ, 2, None, 250, TWIN_LABEL),                  # id 5 — unknown, GROUP BY에서 zz의 첫 그룹(NULL)
    (TIE_AA, 3, "max_tokens", 120, TWIN_LABEL),          # id 6
    (TIE_ZZ, 8, "endTurn", 400, TWIN_LABEL),             # id 7 — end_turn 별칭, GROUP BY에서 "end_turn"(id 3)보다 먼저
    (TIE_ZZ, 9, "", 10, TWIN_LABEL),                     # id 8 — unknown, zz의 가장 작은 output_tokens
    (STATS_TIE, 1, "end_turn", 300, "Stats Tie A"),      # id 9 — 가장 최근 시각, 먼저 본 행
    (STATS_TIE, 1, "end_turn", 300, "Stats Tie B"),      # id 10 — 같은 시각, 나중에 본 행
    (STATS_TIE, 5, "end_turn", 300, "Stats Tie C"),      # id 11 — 더 이른 시각, 가장 큰 id
)


def _seed_ties(factory) -> None:
    with factory() as db:
        db.add(models.ProbeRun(id=1, prompt="auto", status="completed", is_auto=1, created_at=FROZEN_NOW))
        for row_id, ((model_id, _), offset, reason, out_tok, label) in enumerate(TIE_ROWS, start=1):
            db.add(models.ProbeResult(
                id=row_id, run_id=1, model_id=model_id, model_name=label,
                timestamp=FROZEN_NOW - timedelta(hours=offset), prompt="tie", status="success",
                ttft_ms=400.0 + row_id, total_latency_ms=1500.0 + row_id, input_tokens=600, output_tokens=out_tok,
                tps=40.0, output_text="ok", category="chat-short", stop_reason=reason,
            ))
        db.commit()


@pytest.fixture()
def tie_env(monkeypatch):
    with _serve(monkeypatch, _seed_ties) as served:
        yield served


def test_tie_dataset_separates_first_appearance_from_alphabetical_and_timestamp_order():
    """아래 고정이 헛돌지 않는지 — 쌍둥이의 처음 나온 순서(id), 알파벳 순서, 가장 이른 시각 순서가 서로 다르다."""
    first_id: dict[str, int] = {}
    oldest_h: dict[str, float] = {}
    for row_id, ((model_id, _), offset, *_rest) in enumerate(TIE_ROWS, start=1):
        first_id.setdefault(model_id, row_id)
        oldest_h[model_id] = max(oldest_h.get(model_id, 0.0), offset)
    twins = [TIE_ZZ[0], TIE_AA[0]]
    assert sorted(twins, key=first_id.__getitem__) == [TIE_ZZ[0], TIE_AA[0]]
    assert sorted(twins) == [TIE_AA[0], TIE_ZZ[0]]
    assert sorted(twins, key=lambda m: -oldest_h[m]) == [TIE_AA[0], TIE_ZZ[0]]


def test_stop_reason_twin_rows_and_count_keys_follow_first_appearance_by_id(tie_env):
    client, _ = tie_env
    stop = client.get("/api/analysis/stop-reasons").json()["rows"]
    assert [(r["model_name"], r["model_id"]) for r in stop] == [
        (TWIN_LABEL, TIE_ZZ[0]), (TWIN_LABEL, TIE_AA[0]),
        ("Stats Tie A", STATS_TIE[0]), ("Stats Tie B", STATS_TIE[0]), ("Stats Tie C", STATS_TIE[0]),
    ]
    zz, aa = stop[0], stop[1]
    # 키 = 정규 키가 처음 나온 id 순서. zz의 end_turn은 별칭 "endTurn"(id 7)보다 "end_turn"(id 3)이 먼저 나왔다.
    # 알파벳 순서, 행 수 순서, 가장 이른 시각 순서는 셋 다 이 순서와 다르다.
    assert _canonical(zz["counts"]) == _canonical({"max_tokens": 1, "end_turn": 2, "unknown": 2})
    assert _canonical(zz["percentages"]) == _canonical({"max_tokens": 20.0, "end_turn": 40.0, "unknown": 40.0})
    assert _canonical(aa["counts"]) == _canonical({"end_turn": 1, "tool_use": 1, "max_tokens": 1})
    assert _canonical(aa["percentages"]) == _canonical({"end_turn": 33.3, "tool_use": 33.3, "max_tokens": 33.3})


def test_output_length_twin_rows_follow_first_appearance_by_id(tie_env):
    client, _ = tie_env
    out = client.get("/api/analysis/output-length").json()["rows"]
    assert [(r["model_name"], r["model_id"], r["n"]) for r in out if r["model_name"] == TWIN_LABEL] == [
        (TWIN_LABEL, TIE_ZZ[0], 5), (TWIN_LABEL, TIE_AA[0], 3),
    ]


def test_results_stats_label_is_the_first_row_seen_at_the_latest_timestamp(tie_env):
    """예전 max(group, key=timestamp)는 가장 최근 시각이 같은 행 중 먼저 본 행을 골랐다 — 더 늦은 id나 더 이른 시각이 아니다."""
    client, _ = tie_env
    names = {m["model_id"]: m["model_name"] for m in _stats(client)["models"]}
    assert names[STATS_TIE[0]] == "Stats Tie A"
    assert names[TIE_ZZ[0]] == names[TIE_AA[0]] == TWIN_LABEL


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
    # 비용 화면(24h 기본, 1h~30d)이 부른다. SQL 집계라 메모리는 O(모델)이지만 스캔은 창에 비례한다 — 추이와 같은 30d.
    "/api/cost/summary": ("30d", _OVER_30D, ["30d", "720h", "43200m", "30D", " 7d "]),
    "/api/cost/channel-compare": ("30d", _OVER_30D, ["30d", "720h", "43200m", "30D", " 7d "]),
}
UNREADABLE_WINDOWS = [
    "xd", "1e3h", "d",
    pytest.param("99999999999d", id="timedelta-overflow"),
    pytest.param("9" * 5000 + "h", id="5000-digit-int"),
]


def _probe_result_selects(statements) -> list[tuple[str, dict]]:
    return [(sql, opts) for sql, opts in statements if "FROM probe_results" in sql]


def _items(body: dict) -> list:
    return (body.get("rows") or body.get("families") or body.get("models") or body.get("points")
            or body.get("channels") or [])


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


# 0 이하의 창. 예전에는 0과 음수 창이 now 이후를 하한으로 삼아 빈 응답(200)을 냈고, 아주 큰 음수 창은 상한 검사를
# 지나 now - 창에서 OverflowError(500)가 났다. 상한이 있든 없든 모든 호출자가 DB를 읽기 전에 422다.
NON_POSITIVE_WINDOWS = [
    "0d", "0h", "0m", "-0d", "-5d", "-1m", " -24H ",
    pytest.param("-99999999d", id="negative-overflow"),
]
_ALL_WINDOW_PATHS = list(WINDOW_CAPS)  # window를 받는 공개 조회 엔드포인트 전부


@pytest.mark.parametrize("path", _ALL_WINDOW_PATHS)
@pytest.mark.parametrize("window", NON_POSITIVE_WINDOWS)
def test_zero_or_negative_window_is_422_before_any_scan(env, path, window):
    client, statements = env
    statements.clear()
    resp = client.get(path, params={"window": window})
    assert resp.status_code == 422
    assert "window는 0보다 길어야 합니다" in resp.json()["detail"]
    assert _probe_result_selects(statements) == []


@pytest.mark.parametrize("path", _ALL_WINDOW_PATHS)
def test_window_past_the_datetime_range_is_422_not_500(env, path):
    """timedelta로는 읽히지만(999999999일) now - 창이 서기 1년보다 이른 창 — 예전 상한 없던 cost summary는 500이었다."""
    client, statements = env
    statements.clear()
    resp = client.get(path, params={"window": "999999999d"})
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


# run_id는 1 이상만 받는다. 예전 stats는 기본 24h 창과 31일 하한을 "run_id is None"으로 골랐지만 run_id 필터는
# "if run_id"로 걸어, run_id=0이 두 상한을 모두 건너뛰고 보존 중인 success 행 전체를 읽었다(2026-09-30 통합 리뷰).
# 프런트엔드는 run_id를 참일 때만 보낸다(frontend/src/lib/api.ts fetchResults, fetchStats는 run_id를 보내지 않는다).
_BAD_RUN_IDS = [{"run_id": 0}, {"run_id": -1}, {"run_id": 0, "start_time": "1970-01-01T00:00:00Z"}]


@pytest.mark.parametrize("path", ["/api/results/stats", "/api/results"])
@pytest.mark.parametrize("params", _BAD_RUN_IDS, ids=["zero", "negative", "zero-with-1970-start"])
def test_results_run_id_below_1_is_422_before_any_scan(env, path, params):
    client, statements = env
    statements.clear()
    resp = client.get(path, params=params)
    assert resp.status_code == 422
    (error,) = resp.json()["detail"]
    assert error["loc"] == ["query", "run_id"] and error["type"] == "greater_than_equal"
    assert _probe_result_selects(statements) == []


def test_results_run_id_1_still_reads_the_whole_run(env):
    """run_id=1은 예전 그대로 그 run 하나를 창 없이 읽는다 — stats 행 수는 목록 엔드포인트의 run 1 success 행 수와 같다."""
    client, _ = env
    listed = client.get("/api/results", params={"run_id": 1, "limit": 1000})
    assert listed.status_code == 200
    rows = listed.json()
    assert rows and {r["run_id"] for r in rows} == {1}
    expected: dict[str, int] = {}
    for r in rows:
        if r["status"] == "success":
            expected[r["model_id"]] = expected.get(r["model_id"], 0) + 1
    body = _stats(client, run_id=1)
    assert body["start_time"] is None  # 기본 24h 창을 걸지 않는다
    assert {m["model_id"]: m["count"] for m in body["models"]} == expected
    assert sum(expected.values()) > sum(m["count"] for m in _stats(client)["models"])  # 24h 창보다 넓다


def test_parse_window_keeps_the_no_unit_fallback_and_accepts_long_windows_without_a_cap():
    assert window_spec.parse_window("") == timedelta(hours=24)
    assert window_spec.parse_window("abc") == timedelta(hours=24)  # 단위가 없으면 예전처럼 24h
    assert window_spec.parse_window("7") == timedelta(hours=24)
    assert window_spec.parse_window(" 7D ") == timedelta(days=7)
    assert window_spec.parse_window("45m") == timedelta(minutes=45)
    assert window_spec.parse_window("3650d") == timedelta(days=3650)  # 상한 없는 호출
    cap = timedelta(days=30)
    assert window_spec.parse_window("30d", max_window=cap) == cap
    with pytest.raises(HTTPException) as exc:
        window_spec.parse_window("31d", max_window=cap)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("max_window", [None, timedelta(days=30)])
@pytest.mark.parametrize("spec", ["0d", "0m", "-0h", "-1h", "-99999999d", "999999999d", "800000d"])
def test_parse_window_rejects_non_positive_and_datetime_overflowing_windows(spec, max_window):
    """0 이하와 now - 창이 datetime 범위를 넘는 창은 상한이 없는 호출(max_window=None)에서도 422다."""
    with pytest.raises(HTTPException) as exc:
        window_spec.parse_window(spec, max_window=max_window)
    assert exc.value.status_code == 422
    assert "window" in exc.value.detail


def test_parse_window_overflow_check_uses_now_minus_the_window():
    # 70만 일(약 1916년)은 now - 창이 서기 1년 뒤라 받고, 80만 일(약 2190년)은 그 전이라 422다.
    assert window_spec.parse_window("700000d") == timedelta(days=700000)
    with pytest.raises(HTTPException):
        window_spec.parse_window("800000d")
    assert window_spec.parse_window("+5d") == timedelta(days=5)  # 부호가 붙은 양수는 예전처럼 받는다
