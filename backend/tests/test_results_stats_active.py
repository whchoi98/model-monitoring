"""/api/results/stats?active_only=true — 이력 조회 화면이 대시보드 모델 모니터링과 같은 채널만 보인다 (2026-10-29).

v2.38.0에 수집을 멈춘 Mantle us-east-2, us-west-2 채널은 숨김 패턴에 걸리지 않아 7일, 30일 창의 이력 통계에 남았다
(운영 56행 = 활성 49 + 7). active_only는 요청 시점의 `prober.AVAILABLE_MODELS`(= `/api/models`)에 있는 채널만 집계한다.
파라미터가 없으면 응답은 예전과 같다.
"""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models

ACTIVE = [  # Bedrock은 정적 카탈로그, OpenAI Mantle은 기동 때 등록하는 채널(테스트에서 setitem)
    ("Bedrock Claude Haiku 5.5 (Global)", "global.anthropic.claude-haiku-5-5"),
    ("OpenAI GPT 5.5 (us-east-1)", "openai:us-east-1:openai.gpt-5.5"),
]
STOPPED = [  # v2.38.0 — 행은 남았지만 카탈로그에 없다
    ("OpenAI GPT 5.5 (us-east-2)", "openai:us-east-2:openai.gpt-5.5"),
    ("OpenAI GPT 6 Astra (us-west-2)", "openai:us-west-2:openai.gpt-6-astra"),
]


@pytest.fixture()
def client(monkeypatch):
    from database import get_db
    from routers import results as results_router

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    s = factory()
    now = datetime.now(timezone.utc)
    run = models.ProbeRun(is_auto=1, status="completed", created_at=now, prompt="p")
    s.add(run)
    s.flush()
    for name, mid in [*ACTIVE, *STOPPED]:
        s.add(models.ProbeResult(
            run_id=run.id, model_id=mid, model_name=name, timestamp=now, prompt="p", status="success",
            ttft_ms=500.0, total_latency_ms=1500.0, tps=40.0, input_tokens=100, output_tokens=50,
        ))
    s.commit()
    s.close()

    catalog = results_router.AVAILABLE_MODELS  # prober.AVAILABLE_MODELS와 같은 dict
    for name, mid in ACTIVE:
        monkeypatch.setitem(catalog, mid, name)
    for _, mid in STOPPED:
        assert mid not in catalog

    app = FastAPI()
    app.include_router(results_router.router)

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def _names(client, **params):
    resp = client.get("/api/results/stats", params=params)
    assert resp.status_code == 200
    return sorted(m["model_name"] for m in resp.json()["models"])


def test_active_only_drops_channels_outside_the_catalog(client):
    assert _names(client, active_only="true") == sorted(n for n, _ in ACTIVE)


def test_without_active_only_the_response_is_unchanged(client):
    assert _names(client) == sorted(n for n, _ in [*ACTIVE, *STOPPED])
    assert _names(client, active_only="false") == sorted(n for n, _ in [*ACTIVE, *STOPPED])


def test_active_only_reads_the_catalog_at_request_time(client, monkeypatch):
    """기동 뒤 등록된 채널(CP, OpenAI)도 들어간다 — import 시점의 목록을 복사해 두면 빠진다."""
    from routers import results as results_router

    name, mid = STOPPED[0]
    monkeypatch.setitem(results_router.AVAILABLE_MODELS, mid, name)
    assert _names(client, active_only="true") == sorted(n for n, _ in [*ACTIVE, STOPPED[0]])
