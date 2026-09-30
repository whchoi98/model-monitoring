"""공개 조회 엔드포인트의 응답 골든과 스캔 상한 — 2026-09-30 /analysis OOM 회귀 테스트.

사고(2026-09-30 16:01 UTC, v2.32.0, backend 태스크 1024 MiB): /analysis 화면은
/api/analysis/stop-reasons와 /api/analysis/output-length(기본 7d)를 동시에 부른다. 두 요청이 창 안의
probe_results 행을 prompt, output_text까지 담은 ORM 엔티티로 모두 읽어 메모리가 20%에서 57%로 오르고,
두 번째 로드에서 컨테이너가 OOM(exit 137)으로 죽었다.

응답 골든: 아래 SQLite 데이터셋(시각은 FROZEN_NOW 기준으로 고정)에서 v2.32.0(98af18e) 코드가 낸 응답을
tests/fixtures/read_goldens_v2320.json에 고정했다. 조회 방식을 바꾼 뒤에도 키 순서까지 같아야 한다.
응답을 의도적으로 바꾸는 변경이 아니면 골든을 다시 만들지 않는다(다시 만들 때:
FREEZE_READ_GOLDENS=1 python3.12 -m pytest tests/test_read_scan_bounds.py -k freeze).
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import get_db
from pricing_sources import EPOCH
from routers import analysis as analysis_router
from routers import cost as cost_router
from routers import efficiency as efficiency_router
from routers import reliability as reliability_router
from routers import results as results_router

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "read_goldens_v2320.json"
FREEZE = os.environ.get("FREEZE_READ_GOLDENS") == "1"

FROZEN_NOW = datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)
CATEGORIES = ("chat-short", "reasoning", "code-gen", "summarize", "structured", "translate")

G = ("global.anthropic.claude-sonnet-5", "Bedrock Claude Sonnet 5 (Global)")
G_STALE_LABEL = "Bedrock Claude Sonnet 5 (global)"  # 500h 이전 행의 옛 라벨 — stats는 카탈로그 라벨을 쓴다
US = ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "Bedrock Claude Haiku 4.5 (US)")
IR = ("bedrock:ap-northeast-2:anthropic.claude-opus-5", "Bedrock Claude Opus 5 (ap-northeast-2)")
CP = ("anthropic:claude-sonnet-5", "Anthropic Claude Sonnet 5 (US)")
# 같은 라벨, 다른 id — model_name 정렬 동률. 옛 id(A)는 100h 이전, 새 id(B)는 그 뒤에만 있다.
TWIN_A = ("anthropic:claude-haiku-4-5", "Anthropic Claude Haiku 4.5 (US)")
TWIN_B = ("anthropic:claude-haiku-4-5-20251001", "Anthropic Claude Haiku 4.5 (US)")
OA = ("openai:us-east-1:openai.gpt-6.1-sol", "OpenAI GPT 6.1 Sol (us-east-1)")
OG = ("openai:global:global.openai.gpt-6.1-sol", "OpenAI GPT 6.1 Sol (Global)")
ODD = ("mystery.model-v9", "weird-label")  # 라벨 형식 밖(reliability "Other"), 단가 없음
HIDDEN = ("openai:1p:gpt-5.4", "OpenAI GPT 5.4 (1P)")  # 조회에서 숨김
RENAMED = ("mystery.model-v8", None)  # 카탈로그 밖 id, 13h 이전은 옛 라벨
RENAMED_OLD, RENAMED_NEW = "Bedrock Mystery 8 (Global)", "Bedrock Mystery 8b (Global)"
MODELS = (G, US, IR, CP, TWIN_A, TWIN_B, OA, OG, ODD, HIDDEN, RENAMED)
CATALOG = {G[0]: G[1], US[0]: US[1], IR[0]: IR[1]}  # results/stats 라벨 기준(prober.AVAILABLE_MODELS 대역)

# 오래된 것부터 넣는다 — id 순서 = 시각 순서. 창 경계(6h, 24h, 7d = 168h, 30d = 720h) 양쪽에 행이 있다.
OFFSETS_H = (960, 725, 719, 500, 300, 170, 160, 100, 50, 30, 23, 20, 13, 11, 7, 5, 3, 2, 1, 0.25)
STOP_REASONS = ("end_turn", "endTurn", "max_tokens", "END-TURN", None, "tool_use", "maxTokens", "",
                "stop_sequence", "weird_reason", "end_turn", "guardrail_intervened", "content_filtered",
                "max_tokens", "end_turn")
OUT_TOKENS = (0, 42, 99, 100, 180, 249, 250, 380, 499, 500, 777, 999, 1000, 1500, 1999, 2000, 3100,
              3999, 4000, 5200, 512, 512, 80, 80, 400)
ERRORS = ("ThrottlingException: Rate exceeded", "ServiceUnavailableException", None,
          "ModelStreamErrorException: stream broke", "Connection reset by peer",
          "WallClockTimeout: probe exceeded 90s wall-clock", "Model is overloaded", "weird failure",
          "Internal server error (500)")



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


class _FrozenDatetime(datetime):
    """라우터 모듈의 datetime.now만 FROZEN_NOW로 고정한다(나머지는 datetime 그대로)."""

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW.astimezone(tz) if tz is not None else FROZEN_NOW.replace(tzinfo=None)


def _row_values(k: int, i: int, j: int, model: tuple) -> dict:
    """행 번호 k(전체), 시각 번호 i, 모델 번호 j로 정한 결정적 값."""
    offset = OFFSETS_H[i]
    model_id, label = model
    if model is G and offset >= 500:
        label = G_STALE_LABEL
    if model is RENAMED:
        label = RENAMED_OLD if offset >= 13 else RENAMED_NEW
    status = "error" if k % 9 == 4 else ("overloaded" if k % 13 == 6 else "success")
    ok = status == "success"
    ttft = None if k % 11 == 2 else round(300 + 17.3 * ((k * 7) % 41), 1)
    total = None if k % 14 == 5 else round((ttft or 250.0) + 900.5 + 13.1 * (k % 17), 1)
    out_tok = OUT_TOKENS[(k * 7 + i * 3) % len(OUT_TOKENS)]
    if k % 19 == 7:
        out_tok = None
    elif k % 23 == 11:
        out_tok = -1
    return dict(
        run_id=2 if i >= 17 and j in (0, 3) else 1,
        model_id=model_id,
        model_name=label,
        timestamp=FROZEN_NOW - timedelta(hours=offset),
        prompt=f"prompt {k} " + "x" * 200,
        status=status,
        ttft_ms=ttft if ok else None,
        total_latency_ms=total if ok else None,
        server_latency_ms=(None if k % 5 == 1 else round(total * 0.8, 2)) if ok and total else None,
        input_tokens=(500 + 37 * (k % 29)) if ok else None,
        output_tokens=out_tok if ok else None,
        tps=(None if k % 12 == 9 else round(20 + 3.7 * (k % 23), 2)) if ok else None,
        output_text=f"output {k} " + "y" * 400 if ok else None,
        error_message=None if ok else ERRORS[(k * 5 + i) % len(ERRORS)],
        category=None if k % 17 == 3 else CATEGORIES[(i + j) % len(CATEGORIES)],
        stop_reason=STOP_REASONS[(k * 4 + i) % len(STOP_REASONS)] if ok else None,
    )


def _seed(factory) -> None:
    with factory() as db:
        db.add(models.ProbeRun(id=1, prompt="auto", status="completed", is_auto=1, created_at=FROZEN_NOW))
        db.add(models.ProbeRun(id=2, prompt="manual", status="completed", is_auto=0, created_at=FROZEN_NOW))
        prices = {G[0]: (2.0, 10.0), US[0]: (1.1, 5.5), IR[0]: (5.5, 27.5), CP[0]: (2.0, 10.0),
                  TWIN_A[0]: (1.0, 5.0), TWIN_B[0]: (1.0, 5.0), OA[0]: (2.2, 11.0), OG[0]: (2.0, 10.0),
                  HIDDEN[0]: (2.75, 16.5)}
        for model_id, (inp, out) in prices.items():
            db.add(models.PriceHistory(model_id=model_id, family_key="test", channel="global",
                                       input_per_mtok=inp, output_per_mtok=out, effective_from=EPOCH,
                                       source_id="seed", status="seed", observed_at=None))
        # 창 안의 단가 변경 — 12시간 전부터 G는 $3/$15
        change_at = FROZEN_NOW - timedelta(hours=12)
        db.add(models.PriceHistory(model_id=G[0], family_key="test", channel="global", input_per_mtok=3.0,
                                   output_per_mtok=15.0, effective_from=change_at, source_id="offer:test",
                                   status="verified", observed_at=change_at))
        db.commit()
        k = 0
        for i, offset in enumerate(OFFSETS_H):
            for j, model in enumerate(MODELS):
                if (model is TWIN_A and offset < 100) or (model is TWIN_B and offset >= 100):
                    continue
                db.add(models.ProbeResult(**_row_values(k, i, j, model)))
                k += 1
        db.commit()


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P)")
    _seed(factory)

    app = FastAPI()
    for module in (analysis_router, reliability_router, efficiency_router, cost_router, results_router):
        app.include_router(module.router)

    def db_override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    # 라우트를 만든 뒤에 바꾼다 — Query 파라미터 타입(datetime)은 라우트 생성 때 이미 해석됐다.
    for module in (analysis_router, reliability_router, efficiency_router, cost_router, results_router):
        monkeypatch.setattr(module, "datetime", _FrozenDatetime)
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
