"""Persistent anonymous browser counts: no provider calls and no real visitor data."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, update
from sqlalchemy.orm import sessionmaker

from database import Base, get_db
from main import app


ORIGIN = "https://monitor.test"
HEADERS = {"Origin": ORIGIN, "x-llm-monitor-client": "1"}
COOKIE = "llm_monitor_visitor"


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv("PRESENCE_ALLOWED_ORIGINS", ORIGIN)
    pg_url = os.environ.get("PRESENCE_TEST_DATABASE_URL")
    admin = None
    schema = f"presence_{uuid.uuid4().hex}"
    if pg_url:
        admin = create_engine(pg_url)
        with admin.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(pg_url, connect_args={"options": f"-c search_path={schema}"})
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'presence.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = session
    client = TestClient(app, base_url=ORIGIN)
    yield client, factory
    client.close()
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()
    if admin is not None:
        with admin.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def heartbeat(client):
    return client.post("/api/presence", headers=HEADERS, json={})


def test_read_bootstraps_a_signed_cookie_without_inventing_a_visit(site):
    client, _ = site
    response = client.get("/api/presence")
    assert response.status_code == 200
    payload = response.json()
    assert (payload["active_visitors"], payload["total_visitors"], payload["initial_total"]) == (0, 10000, 10000)
    assert payload["window_seconds"] == 90
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert "path=/api/presence" in cookie
    first = client.cookies.get(COOKIE)
    assert first
    assert client.get("/api/presence").json()["total_visitors"] == 10000
    assert client.cookies.get(COOKIE) == first


def test_a_browser_is_counted_once_across_heartbeats_and_new_app_clients(site):
    client, _ = site
    assert client.get("/api/presence").status_code == 200
    first = heartbeat(client)
    assert first.status_code == 200
    assert (first.json()["active_visitors"], first.json()["total_visitors"]) == (1, 10001)
    assert datetime.fromisoformat(first.json()["counting_since"]).tzinfo is not None
    for _ in range(3):
        assert heartbeat(client).json()["total_visitors"] == 10001
    another = TestClient(app, base_url=ORIGIN)
    try:
        another.cookies.set(COOKIE, client.cookies.get(COOKIE), domain="monitor.test", path="/api/presence")
        assert heartbeat(another).json()["total_visitors"] == 10001
    finally:
        another.close()


def test_expired_activity_does_not_erase_total_or_recount_a_returning_browser(site):
    client, factory = site
    assert client.get("/api/presence").status_code == 200
    assert heartbeat(client).json()["total_visitors"] == 10001
    from models import SiteVisitor
    with factory.begin() as db:
        db.execute(update(SiteVisitor).values(last_seen=datetime.now(timezone.utc) - timedelta(seconds=91)))
    expired = client.get("/api/presence").json()
    assert (expired["active_visitors"], expired["total_visitors"]) == (0, 10001)
    returned = heartbeat(client).json()
    assert (returned["active_visitors"], returned["total_visitors"]) == (1, 10001)


def test_parallel_tabs_cannot_double_count_the_same_cookie(site):
    client, _ = site
    assert client.get("/api/presence").status_code == 200
    visitor = client.cookies.get(COOKIE)

    def visit(_):
        another = TestClient(app, base_url=ORIGIN)
        another.cookies.set(COOKIE, visitor, domain="monitor.test", path="/api/presence")
        try:
            response = heartbeat(another)
            assert response.status_code == 200
            return response.json()["total_visitors"]
        finally:
            another.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        totals = list(pool.map(visit, range(12)))
    assert totals == [10001] * 12
    assert client.get("/api/presence").json()["active_visitors"] == 1


def test_new_browsers_increment_atomically_and_survive_new_database_sessions(site):
    client, _ = site
    assert client.get("/api/presence").status_code == 200

    def visit(_):
        another = TestClient(app, base_url=ORIGIN)
        try:
            assert another.get("/api/presence").status_code == 200
            response = heartbeat(another)
            assert response.status_code == 200
        finally:
            another.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(visit, range(12)))
    result = client.get("/api/presence").json()
    assert (result["active_visitors"], result["total_visitors"]) == (12, 10012)


def test_untrusted_origins_missing_cookies_and_client_counts_cannot_change_the_total(site):
    client, _ = site
    assert heartbeat(client).status_code == 401
    assert client.get("/api/presence").status_code == 200
    assert client.post("/api/presence", headers={**HEADERS, "Origin": "https://evil.test"}, json={}).status_code == 403
    assert client.post("/api/presence", headers={"Origin": ORIGIN}, json={}).status_code == 403
    assert client.post("/api/presence", headers=HEADERS, json={"total_visitors": 900000}).status_code == 422
    valid = client.cookies.get(COOKIE)
    client.cookies.set(COOKIE, valid[:-1] + ("0" if valid[-1] != "0" else "1"), domain="monitor.test", path="/api/presence")
    assert heartbeat(client).status_code == 401
    assert client.get("/api/presence").json()["total_visitors"] == 10000


def test_storage_failure_is_unavailable_instead_of_a_fabricated_zero(site):
    client, factory = site
    assert client.get("/api/presence").status_code == 200
    assert heartbeat(client).json()["total_visitors"] == 10001
    with factory.begin() as db:
        db.execute(text("DROP TABLE site_visitors"))
    response = client.get("/api/presence")
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert "total_visitors" not in response.json()


def test_failed_increment_rolls_back_the_first_visit_marker(site):
    client, factory = site
    assert client.get("/api/presence").status_code == 200
    assert heartbeat(client).json()["total_visitors"] == 10001
    from models import SitePresenceTotal
    with factory.begin() as db:
        db.execute(update(SitePresenceTotal).values(total_visitors=9_007_199_254_740_991))
    other = TestClient(app, base_url=ORIGIN)
    try:
        assert other.get("/api/presence").status_code == 200
        assert heartbeat(other).status_code == 503
        with factory.begin() as db:
            db.execute(update(SitePresenceTotal).values(total_visitors=10001))
        assert heartbeat(other).json()["total_visitors"] == 10002
    finally:
        other.close()


@pytest.mark.skipif(not os.environ.get("PRESENCE_TEST_DATABASE_URL"), reason="isolated PostgreSQL proof")
def test_concurrent_postgres_startups_create_the_schema_once(monkeypatch):
    import database
    from sqlalchemy import inspect
    url = os.environ["PRESENCE_TEST_DATABASE_URL"]
    schema = f"presence_startup_{uuid.uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
    monkeypatch.setattr(database, "engine", engine)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: database.create_tables(), range(4)))
        assert {"site_visitors", "site_presence_totals"} <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
        with admin.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
