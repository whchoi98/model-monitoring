"""routers/pricing.py — /api/pricing, /api/pricing/export, /api/admin/pricing/* (v2.30.0, ADR-030).

In-memory SQLite, FastAPI TestClient, no network. prober.AVAILABLE_MODELS is replaced per test so the
active set is deterministic; the 60 s cache is cleared around every test.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import prober
from auth import create_access_token
from database import get_db
from price_history import as_utc
from pricing_export import BOM
from pricing_sources import DISCLAIMER, EPOCH
from routers import pricing as pricing_router
from tests._pricing_dataset import add_price

MODELS = {
    "global.anthropic.claude-opus-5-5": "Bedrock Claude Opus 5.5 (Global)",
    "us.anthropic.claude-opus-5-5": "Bedrock Claude Opus 5.5 (US)",
    "openai:us-east-1:openai.gpt-5.4": "OpenAI GPT 5.4 (us-east-1)",
    "openai:us-east-2:openai.gpt-5.4": "OpenAI GPT 5.4 (us-east-2)",
    "openai:1p:gpt-5.4": "OpenAI GPT 5.4 (1P)",  # hidden by HIDDEN_MODEL_PATTERNS
}
OPUS_OFFER = "offer:offer-7sp77cpl4rveu"
G54_OFFER = "offer:offer-5l5a5izq5fbec"


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(MODELS))
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P)")
    now = datetime.now(timezone.utc)
    with factory() as db:
        db.add(models.User(username="admin", password_hash="x", approved=1))
        db.add(models.User(username="viewer@example.com", password_hash="x", approved=1))
        db.add(models.PriceSyncRun(started_at=now - timedelta(hours=1), finished_at=now - timedelta(minutes=59),
                                   status="completed"))
        add_price(db, "global.anthropic.claude-opus-5-5", 4.0, 20.0, observed_at=now - timedelta(hours=1),
                  source_id=OPUS_OFFER)
        add_price(db, "us.anthropic.claude-opus-5-5", 4.4, 22.0, observed_at=now - timedelta(hours=1),
                  source_id=OPUS_OFFER)
        for region in ("us-east-1", "us-east-2"):
            add_price(db, f"openai:{region}:openai.gpt-5.4", 2.75, 16.5, observed_at=now - timedelta(hours=1),
                      source_id=G54_OFFER)
        add_price(db, "openai:1p:gpt-5.4", 2.75, 16.5, source_id=G54_OFFER)
        db.commit()

    app = FastAPI()
    app.include_router(pricing_router.router)
    app.include_router(pricing_router.admin_router)

    def db_override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    pricing_router.invalidate_cache()
    with TestClient(app) as client:
        yield factory, client, now
    pricing_router.invalidate_cache()
    engine.dispose()


def _auth(username):
    return {"Authorization": f"Bearer {create_access_token(username)}"}


def _pending(factory, model_id, inp, out, *, effective_from, observed_at):
    with factory() as db:
        row = add_price(db, model_id, inp, out, effective_from=effective_from, status="pending_review",
                        observed_at=observed_at, source_id=OPUS_OFFER)
        db.commit()
        return row.id


def test_pricing_shape_and_active_set(env):
    _, client, _ = env
    body = client.get("/api/pricing").json()
    assert body["currency"] == "USD" and body["unit"] == "per_1m_tokens"
    assert body["disclaimer"] == {"en": DISCLAIMER["en"], "ko": DISCLAIMER["ko"]}
    assert [f["family_key"] for f in body["families"]] == ["claude-opus-5-5", "gpt-5.4"]
    for family in body["families"]:
        assert set(family["tiers"]) == {"cp", "global", "us", "in_region"}
        assert isinstance(family["tiers"]["in_region"], list)
    gpt54 = body["families"][1]["tiers"]["in_region"]
    assert [(e["regions"], e["input"], e["output"]) for e in gpt54] == [(["us-east-1", "us-east-2"], 2.75, 16.5)]
    assert "openai:1p:gpt-5.4" not in body["models"]  # hidden channel never appears
    assert body["models"]["us.anthropic.claude-opus-5-5"] == {"input": 4.4, "output": 22, "verification": "verified"}
    refs = {r["n"]: r["id"] for r in body["references"]}
    for family in body["families"]:
        for tier in ("cp", "global", "us"):
            cell = family["tiers"][tier]
            if cell:
                assert [refs[n] for n in cell["footnotes"]] == cell["source_ids"]


def test_cp_ids_observed_in_the_last_30_days_stay_in_the_table_when_discovery_failed(env):
    factory, client, now = env
    with factory() as db:
        add_price(db, "anthropic:claude-opus-5-5", 4.0, 20.0, observed_at=now - timedelta(days=2),
                  source_id="anthropic-pricing")
        add_price(db, "anthropic:claude-opus-4-7", 5.0, 25.0, observed_at=now - timedelta(days=31),
                  source_id="anthropic-pricing")
        db.commit()
    body = client.get("/api/pricing").json()
    assert body["families"][0]["tiers"]["cp"]["model_ids"] == ["anthropic:claude-opus-5-5"]
    assert "anthropic:claude-opus-4-7" not in body["models"]  # older than 30 days


def test_payload_is_cached_for_60_seconds(env, monkeypatch):
    factory, client, now = env
    clock = [1000.0]
    monkeypatch.setattr(pricing_router, "_monotonic", lambda: clock[0])
    assert client.get("/api/pricing").json()["pending_review"] == 0
    _pending(factory, "us.anthropic.claude-opus-5-5", 9.0, 45.0, effective_from=now, observed_at=now)
    clock[0] += 59.0
    assert client.get("/api/pricing").json()["pending_review"] == 0  # still cached
    clock[0] += 1.0
    assert client.get("/api/pricing").json()["pending_review"] == 1  # 60 s elapsed


def test_a_build_that_overlaps_a_cache_clear_is_not_cached(env, monkeypatch):
    _, client, _ = env
    monkeypatch.setattr(pricing_router, "_monotonic", lambda: 1000.0)
    builds = []
    real_build = pricing_router.build_pricing_payload

    def build_then_clear(*args, **kwargs):
        builds.append(1)
        payload = real_build(*args, **kwargs)
        if len(builds) == 1:
            pricing_router.invalidate_cache()  # an approve/reject commits while this build runs
        return payload

    monkeypatch.setattr(pricing_router, "build_pricing_payload", build_then_clear)
    assert client.get("/api/pricing").status_code == 200
    assert client.get("/api/pricing").status_code == 200
    assert len(builds) == 2  # the first (possibly stale) result was returned but not cached
    assert client.get("/api/pricing").status_code == 200
    assert len(builds) == 2  # the second one was cached


def test_approve_keeps_effective_from_clears_cache_and_warns_about_later_rows(env):
    factory, client, now = env
    change_at = now - timedelta(minutes=30)
    row_id = _pending(factory, "us.anthropic.claude-opus-5-5", 9.0, 45.0, effective_from=change_at,
                      observed_at=change_at)
    with factory() as db:
        add_price(db, "us.anthropic.claude-opus-5-5", 5.0, 25.0, effective_from=now - timedelta(minutes=10),
                  status="verified", observed_at=now - timedelta(minutes=10), source_id=OPUS_OFFER)
        db.commit()
    before = client.get("/api/pricing").json()
    assert before["pending_review"] == 1
    assert before["families"][0]["tiers"]["us"]["pending"]["id"] == row_id

    res = client.post(f"/api/admin/pricing/pending/{row_id}/approve", headers=_auth("admin"))
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True and body["status"] == "verified"
    assert body["effective_from"] == change_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert len(body["warnings"]) == 1 and re.search(r"5 / 25", body["warnings"][0])
    with factory() as db:
        row = db.get(models.PriceHistory, row_id)
        assert row.status == "verified"
        assert as_utc(row.effective_from) == change_at

    after = client.get("/api/pricing").json()  # cache cleared by approve
    assert after["pending_review"] == 0
    assert after["families"][0]["tiers"]["us"]["pending"] is None
    assert after["models"]["us.anthropic.claude-opus-5-5"]["input"] == 5  # later verified row still wins now


def test_approve_warns_about_a_verified_row_with_the_same_start_and_a_higher_id(env):
    factory, client, now = env
    change_at = now - timedelta(minutes=30)
    with factory() as db:  # same start, lower id: the approved row wins over it, no warning
        add_price(db, "us.anthropic.claude-opus-5-5", 6.0, 30.0, effective_from=change_at, status="verified",
                  observed_at=change_at, source_id=OPUS_OFFER)
        db.commit()
    row_id = _pending(factory, "us.anthropic.claude-opus-5-5", 9.0, 45.0, effective_from=change_at,
                      observed_at=change_at)
    with factory() as db:  # same start, higher id: it stays ahead of the approved row in the price lookup
        later_id = add_price(db, "us.anthropic.claude-opus-5-5", 5.0, 25.0, effective_from=change_at,
                             status="verified", observed_at=change_at, source_id=OPUS_OFFER).id
        db.commit()
    body = client.post(f"/api/admin/pricing/pending/{row_id}/approve", headers=_auth("admin")).json()
    assert len(body["warnings"]) == 1 and body["warnings"][0].startswith(f"id {later_id}의 단가 5 / 25가 ")
    assert client.get("/api/pricing").json()["models"]["us.anthropic.claude-opus-5-5"]["input"] == 5


def test_approve_no_baseline_row_applies_from_1970(env):
    factory, client, now = env
    row_id = _pending(factory, "openai:us-east-1:openai.gpt-5.4", 3.0, 18.0, effective_from=EPOCH, observed_at=now)
    listed = client.get("/api/admin/pricing/pending", headers=_auth("admin")).json()["pending"]
    assert [(p["id"], p["reason"]) for p in listed] == [(row_id, "no_baseline")]
    res = client.post(f"/api/admin/pricing/pending/{row_id}/approve", headers=_auth("admin")).json()
    assert res["effective_from"] == "1970-01-01T00:00:00Z"
    assert res["warnings"] == []


def test_reject_marks_rejected_and_clears_cache(env):
    factory, client, now = env
    row_id = _pending(factory, "us.anthropic.claude-opus-5-5", 9.0, 45.0, effective_from=now, observed_at=now)
    assert client.get("/api/pricing").json()["pending_review"] == 1
    res = client.post(f"/api/admin/pricing/pending/{row_id}/reject", headers=_auth("admin"))
    assert res.status_code == 200 and res.json()["status"] == "rejected"
    assert client.get("/api/pricing").json()["pending_review"] == 0
    again = client.post(f"/api/admin/pricing/pending/{row_id}/approve", headers=_auth("admin"))
    assert again.status_code == 409  # only pending_review rows can be decided
    assert again.json()["detail"] == f"단가 행 {row_id}는 검토 대기 상태가 아닙니다 (현재: rejected)"
    missing = client.post("/api/admin/pricing/pending/99999/reject", headers=_auth("admin"))
    assert missing.status_code == 404 and missing.json()["detail"] == "단가 행 99999을(를) 찾을 수 없습니다"


def test_pending_list_reports_current_value_and_change_ratio(env):
    factory, client, now = env
    row_id = _pending(factory, "us.anthropic.claude-opus-5-5", 6.6, 44.0, effective_from=now, observed_at=now)
    listed = client.get("/api/admin/pricing/pending", headers=_auth("admin")).json()["pending"]
    assert listed == [{
        "id": row_id, "model_id": "us.anthropic.claude-opus-5-5", "family_key": "claude-opus-5-5", "channel": "us",
        "reason": "changed", "current": {"input": 4.4, "output": 22.0}, "new": {"input": 6.6, "output": 44.0},
        "change": {"input": 0.5, "output": 1.0}, "source_id": OPUS_OFFER,
        "effective_from": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }]


@pytest.mark.parametrize("method,path", [
    ("get", "/api/admin/pricing/pending"),
    ("post", "/api/admin/pricing/pending/1/approve"),
    ("post", "/api/admin/pricing/pending/1/reject"),
])
def test_admin_endpoints_require_the_admin_account(env, method, path):
    _, client, _ = env
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers=_auth("viewer@example.com")).status_code == 403


@pytest.mark.parametrize("fmt,content_type,ext", [
    ("csv", "text/csv; charset=utf-8", "csv"),
    ("md", "text/markdown; charset=utf-8", "md"),
    ("json", "application/json", "json"),
])
def test_export_headers_and_bodies(env, fmt, content_type, ext):
    _, client, _ = env
    res = client.get(f"/api/pricing/export?format={fmt}&lang=en")
    assert res.status_code == 200
    assert res.headers["content-type"] == content_type
    today = datetime.now(timezone.utc).date().isoformat()
    assert res.headers["content-disposition"] == f'attachment; filename="llm-monitor-unit-prices-{today}.{ext}"'
    text = res.content.decode("utf-8")
    if fmt == "csv":
        assert text.startswith(BOM + '"# ' + DISCLAIMER["en"] + '"\n')
    elif fmt == "md":
        assert text.startswith("> " + DISCLAIMER["en"] + "\n")
        assert text.rstrip("\n").endswith("> " + DISCLAIMER["en"])
    else:
        assert res.json() == client.get("/api/pricing").json()


def test_export_lang_defaults_to_korean(env):
    _, client, _ = env
    text = client.get("/api/pricing/export?format=md").content.decode("utf-8")
    assert text.startswith("> " + DISCLAIMER["ko"] + "\n")


@pytest.mark.parametrize("query", ["format=xlsx", "format=csv&lang=ja", ""])
def test_export_rejects_unknown_format_or_lang(env, query):
    _, client, _ = env
    assert client.get(f"/api/pricing/export?{query}").status_code == 422


def test_main_registers_both_pricing_routers():
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "from routers import pricing as pricing_router" in src
    assert "app.include_router(pricing_router.router)" in src
    assert "app.include_router(pricing_router.admin_router)" in src


def test_hidden_model_patterns_drop_classifiable_channels(env, monkeypatch):
    _, client, _ = env
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P),(us-east-2)")
    body = client.get("/api/pricing").json()
    assert "openai:us-east-2:openai.gpt-5.4" not in body["models"]
    assert "openai:us-east-1:openai.gpt-5.4" in body["models"]
