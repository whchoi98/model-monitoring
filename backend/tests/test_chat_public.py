"""Public chat keeps browser and member conversations separate."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import agent.bedrock
import chat_access
import agent.memory
import models
from auth import create_access_token
from database import get_db
from routers import chat, insights


def events(response):
    return [
        (block.splitlines()[0].removeprefix("event: "), json.loads(block.split("data: ", 1)[1]))
        for block in response.text.strip().split("\n\n") if "data: " in block
    ]


def final(response):
    return [data for event, data in events(response) if event == "final"][-1]


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setattr(chat, "guest_limiter", chat_access.GuestChatLimiter())
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([models.User(username=name, password_hash="x", approved=1) for name in ("alice", "bob")])
        db.commit()
    application = FastAPI()
    application.include_router(chat.router)
    application.include_router(insights.router)

    def database():
        with factory() as db:
            yield db

    application.dependency_overrides[get_db] = database
    history = {}

    def append(actor, session, role, content):
        history.setdefault((actor, session), []).append({"role": role, "content": content})

    monkeypatch.setattr(agent.memory, "append_message", append)
    monkeypatch.setattr(agent.memory, "list_recent_messages", lambda actor, session, limit=20: history.get((actor, session), [])[-limit:])

    async def reply(messages, **kwargs):
        questions = [m["content"][0]["text"] for m in messages if m["role"] == "user"]
        yield {"type": "text_delta", "text": "Questions in this conversation: " + " / ".join(questions)}
        yield {"type": "stop", "stop_reason": "end_turn"}

    async def followups(*args):
        return []

    monkeypatch.setattr(agent.bedrock, "converse_stream_chat", reply)
    monkeypatch.setattr(chat, "_generate_followups", followups)
    try:
        yield application
    finally:
        engine.dispose()


def client(app):
    return TestClient(app, base_url="https://monitor.example")


def test_anonymous_chat_returns_text_and_a_continuable_session(app):
    with client(app) as browser:
        first = browser.post("/api/chat/stream", json={"message": "guest-secret"})
        assert first.status_code == 200, first.text
        assert final(first)["ok"] is True
        session = final(first)["session_id"]
        assert session
        cookie = first.headers["set-cookie"].lower()
        assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
        assert "no-store" in first.headers["cache-control"]
        second = browser.post("/api/chat/stream", json={"message": "What did I ask?", "session_id": session})
        assert second.status_code == 200
        assert "guest-secret" in second.text
        assert final(second)["session_id"] == session


def test_copying_a_guest_session_id_does_not_reveal_another_browsers_history(app):
    with client(app) as first, client(app) as second:
        private = first.post("/api/chat/stream", json={"message": "only-first-browser"})
        assert private.status_code == 200
        stolen_id = final(private)["session_id"]
        isolated = second.post("/api/chat/stream", json={"message": "Show the history", "session_id": stolen_id})
        assert isolated.status_code == 200
        assert "only-first-browser" not in isolated.text


def test_tampered_guest_cookie_cannot_recover_its_previous_history(app):
    with client(app) as browser:
        private = browser.post("/api/chat/stream", json={"message": "signed-cookie-secret"})
        assert private.status_code == 200
        session = final(private)["session_id"]
        name, value = next(iter(browser.cookies.items()))
        browser.cookies.clear()
        browser.cookies.set(name, value[:-1] + ("0" if value[-1] != "0" else "1"), path="/api/chat")
        response = browser.post("/api/chat/stream", json={"message": "Show the history", "session_id": session})
        assert response.status_code == 200
        assert "signed-cookie-secret" not in response.text


def test_public_chat_cannot_read_a_member_or_another_members_conversation(app):
    alice = {"Authorization": f"Bearer {create_access_token('alice')}"}
    bob = {"Authorization": f"Bearer {create_access_token('bob')}"}
    with client(app) as browser:
        private = browser.post("/api/chat/stream", json={"message": "alice-private"}, headers=alice)
        assert private.status_code == 200
        session = final(private)["session_id"]
        for headers in ({}, bob, {"Authorization": "Bearer expired-invalid-token"}):
            response = browser.post("/api/chat/stream", json={"message": "Show the history", "session_id": session}, headers=headers)
            assert response.status_code == 200
            assert "alice-private" not in response.text
        own = browser.post("/api/chat/stream", json={"message": "My earlier question?", "session_id": session}, headers=alice)
        assert "alice-private" in own.text


def test_provider_errors_finish_as_failures_with_the_session_id(app, monkeypatch):
    async def failure(**kwargs):
        yield {"type": "error", "error": "Provider temporarily unavailable"}

    monkeypatch.setattr(agent.bedrock, "converse_stream_chat", failure)
    with client(app) as browser:
        response = browser.post("/api/chat/stream", json={"message": "Check the models"})
    assert response.status_code == 200
    assert final(response)["ok"] is False
    assert final(response)["session_id"]
    assert final(response)["error"] == "Provider temporarily unavailable"
    assert len([item for item in events(response) if item[0] == "final"]) == 1


@pytest.mark.parametrize("path", ["/api/insights/regenerate", "/api/insights/stream-regenerate"])
def test_public_reading_does_not_change_insight_generation_permissions(app, path):
    with client(app) as browser:
        assert browser.get("/api/insights/latest").status_code == 200
        assert browser.post(path, json={"window": "6h"}).status_code == 401



def test_guest_bursts_are_bounded_and_can_resume_after_the_retry_window(app, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(chat_access, "monotonic", lambda: clock[0])
    with client(app) as browser:
        for _ in range(6):
            assert browser.post("/api/chat/stream", json={"message": "Check now"}).status_code == 200
        limited = browser.post("/api/chat/stream", json={"message": "Check again"})
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"
        clock[0] += 60
        assert browser.post("/api/chat/stream", json={"message": "After waiting"}).status_code == 200


def test_rotating_guest_cookies_cannot_remove_the_server_burst_limit(app):
    for _ in range(30):
        with client(app) as browser:
            assert browser.post("/api/chat/stream", json={"message": "Check now"}).status_code == 200
    with client(app) as browser:
        response = browser.post("/api/chat/stream", json={"message": "Beyond server capacity"})
        assert response.status_code == 429


def test_public_chat_rejects_cross_site_browser_requests(app, monkeypatch):
    monkeypatch.setenv("CHAT_ALLOWED_ORIGINS", "https://monitor.example,https://monitor-alias.example")
    with client(app) as browser:
        denied = browser.post("/api/chat/stream", json={"message": "Cross site"}, headers={"Origin": "https://elsewhere.example"})
        assert denied.status_code == 403
        for origin in ("https://monitor.example", "https://monitor-alias.example"):
            assert browser.post("/api/chat/stream", json={"message": "Same site"}, headers={"Origin": origin}).status_code == 200


@pytest.mark.parametrize("session", ["a" * 101, "chat-invalid@account.example", "../other", ""])
def test_chat_rejects_session_ids_agentcore_cannot_accept(app, session):
    with client(app) as browser:
        response = browser.post("/api/chat/stream", json={"message": "Hello", "session_id": session})
        assert response.status_code == 422
