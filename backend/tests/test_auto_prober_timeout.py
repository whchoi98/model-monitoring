"""AutoProber cycle vs one hung model (v2.28.2 hotfix).

2026-09-23 장애: 모델 하나(Mantle GPT-5.6 Sol)가 끝나지 않자 future.result(timeout=120)이 run 전체를
failed로 만들었고, `with ThreadPoolExecutor` 종료가 멈춘 스레드를 join해 태스크가 30~46분 RUNNING으로
남았다. 이제 그 모델만 오류 행으로 기록되고 run은 completed로 끝나며 멈춘 스레드를 기다리지 않는다.
늦게 끝난 워커의 결과는 버려져 (run_id, model_id) 행이 중복되지 않는다.

All records live in a file-backed SQLite DB (one connection per session, safe across worker threads).
"""

import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import auto_prober as worker
import models

HUNG = "openai:us-east-1:openai.gpt-5.6-sol"


@pytest.fixture()
def env(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cycle.db'}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "_get_bedrock_client", lambda region: object())
    monkeypatch.setattr(worker, "_get_region_for_model", lambda mid: "us-east-1")
    monkeypatch.setattr(worker, "_CYCLE_POLL_SECONDS", 0.02)
    monkeypatch.setattr(worker.auto_prober, "current_cycle_running", False)
    monkeypatch.setenv("RETENTION_DAYS", "0")
    release = threading.Event()
    yield factory, release
    release.set()  # 테스트가 실패해도 멈춘 가짜 워커를 풀어 준다
    engine.dispose()


def _write_success(db, run_id, model_id, model_name, prompt, category):
    row = models.ProbeResult(
        run_id=run_id, model_id=model_id, model_name=model_name, prompt=prompt,
        status="success", category=category, iteration=1, ttft_ms=10.0, total_latency_ms=20.0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)


def _rows(factory):
    with factory() as db:
        return [(r.model_id, r.status, r.error_message) for r in
                db.query(models.ProbeResult).order_by(models.ProbeResult.model_id).all()]


def test_hung_probe_gets_timeout_row_and_run_completes(env, monkeypatch):
    factory, release = env
    monkeypatch.setattr(worker, "AVAILABLE_MODELS", {
        "global.anthropic.claude-sonnet-5": "Bedrock Claude Sonnet 5 (Global)",
        HUNG: "OpenAI GPT 5.6 Sol (us-east-1)",
        "us.anthropic.claude-haiku-4-5": "Bedrock Claude Haiku 4.5 (US)",
        "global.anthropic.claude-opus-5": "Bedrock Claude Opus 5 (Global)",
    })
    monkeypatch.setattr(worker, "PROBE_FUTURE_TIMEOUT_S", 0.3)
    late_done = threading.Event()

    def fake_probe(client, model_id, model_name, prompt, temperature,
                   max_tokens, iteration, event_queue, run_id, db, category=None):
        if model_id == HUNG:
            release.wait(10)  # watchdog도 못 끊은 멈춤 — 사이클이 포기한 뒤에야 풀린다
            _write_success(db, run_id, model_id, model_name, prompt, category)  # 늦은 결과
            late_done.set()
            return
        _write_success(db, run_id, model_id, model_name, prompt, category)

    monkeypatch.setattr(worker, "_probe_single_model", fake_probe)

    t0 = time.perf_counter()
    run_id = worker.run_cycle()
    elapsed = time.perf_counter() - t0

    # 멈춘 스레드를 join하지 않고 모델 상한(0.3s) 근처에서 사이클이 끝난다.
    assert elapsed < 3.0
    with factory() as db:
        assert db.get(models.ProbeRun, run_id).status == "completed"
    rows = _rows(factory)
    assert rows == [
        ("global.anthropic.claude-opus-5", "success", None),
        ("global.anthropic.claude-sonnet-5", "success", None),
        (HUNG, "error", "probe did not finish within 0.3s (cycle timeout)"),
        ("us.anthropic.claude-haiku-4-5", "success", None),
    ]
    assert worker.auto_prober.current_cycle_running is False

    # 늦게 풀린 워커의 결과는 버려진다 — (run_id, model_id) 행이 중복되지 않는다.
    release.set()
    assert late_done.wait(5)
    assert _rows(factory) == rows
    with factory() as db:
        [timeout_row] = db.query(models.ProbeResult).filter(models.ProbeResult.model_id == HUNG).all()
        assert timeout_row.run_id == run_id
        assert timeout_row.category is not None and timeout_row.iteration == 1
        assert timeout_row.total_latency_ms is not None and timeout_row.total_latency_ms >= 300


def test_cycle_deadline_records_models_that_never_started(env, monkeypatch):
    """멈춘 워커 3개가 풀(3)을 채우면 대기 중인 모델은 시작조차 못한다 — 사이클 전체 상한이 끊는다."""
    factory, release = env
    hung = {f"global.anthropic.hung-{i}": f"Bedrock Hung {i} (Global)" for i in range(3)}
    queued = "us.anthropic.queued"
    monkeypatch.setattr(worker, "AVAILABLE_MODELS", {**hung, queued: "Bedrock Queued (US)"})
    monkeypatch.setattr(worker, "PROBE_FUTURE_TIMEOUT_S", 30.0)
    monkeypatch.setattr(worker, "CYCLE_DEADLINE_SECONDS", 0.3)
    started, finished = [], []

    def fake_probe(client, model_id, model_name, prompt, temperature,
                   max_tokens, iteration, event_queue, run_id, db, category=None):
        started.append(model_id)
        release.wait(10)
        _write_success(db, run_id, model_id, model_name, prompt, category)
        finished.append(model_id)

    monkeypatch.setattr(worker, "_probe_single_model", fake_probe)

    t0 = time.perf_counter()
    run_id = worker.run_cycle()
    assert time.perf_counter() - t0 < 3.0

    with factory() as db:
        assert db.get(models.ProbeRun, run_id).status == "completed"
    rows = dict((m, (s, e)) for m, s, e in _rows(factory))
    for model_id in hung:
        assert rows[model_id] == ("error", "probe did not finish before the 0.3s cycle deadline (cycle timeout)")
    assert rows[queued] == ("error", "probe not started before the 0.3s cycle deadline (cycle timeout)")

    release.set()
    deadline = time.monotonic() + 5.0
    while len(finished) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sorted(finished) == sorted(hung)  # 멈췄던 워커 3개가 모두 늦게 끝났고
    assert len(_rows(factory)) == 4  # 그 늦은 결과 3건은 모두 버려졌다
    assert queued not in started  # 취소된 대기 작업은 실행되지 않는다


def test_worker_exception_still_fails_the_run(env, monkeypatch):
    """타임아웃이 아닌 워커 예외(결과 저장 실패 등)는 기존대로 run을 failed로 만든다."""
    factory, _ = env
    monkeypatch.setattr(worker, "AVAILABLE_MODELS", {"global.anthropic.a": "Bedrock A (Global)"})

    def broken_probe(*args, **kwargs):
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(worker, "_probe_single_model", broken_probe)
    with pytest.raises(RuntimeError, match="1 model probes did not finish normally"):
        worker.run_cycle()
    with factory() as db:
        assert db.query(models.ProbeRun).one().status == "failed"
    assert _rows(factory) == []


def test_worker_commit_before_abandon_means_no_timeout_row(env):
    """경합: 워커가 먼저 커밋했으면 사이클은 오류 행을 쓰지 않는다 (abandon=False)."""
    factory, _ = env
    slot = worker._ProbeSlot("m", "M")
    assert slot.begin()
    session = worker._SlotSession(factory(), slot)
    _write_success(session, 1, "m", "M", "p", "chat-short")
    session.close()
    assert slot.committed
    assert slot.abandon() is False
    assert [r[:2] for r in _rows(factory)] == [("m", "success")]


def test_abandon_before_commit_discards_the_late_row(env):
    factory, _ = env
    slot = worker._ProbeSlot("m", "M")
    assert slot.begin()
    assert slot.abandon() is True
    session = worker._SlotSession(factory(), slot)
    _write_success(session, 1, "m", "M", "p", "chat-short")  # commit → rollback, refresh → no-op
    session.close()
    assert _rows(factory) == []
    # 시작 전에 포기된 모델은 워커가 프로브를 시작하지 않는다.
    fresh = worker._ProbeSlot("n", "N")
    assert fresh.abandon() is True
    assert fresh.begin() is False


def test_real_probe_through_an_abandoned_slot_writes_nothing_and_does_not_raise(env, monkeypatch):
    """실제 _probe_single_model(성공 경로: add → commit → refresh → id/timestamp 읽기)이 포기된 슬롯의
    프록시 세션을 거치면 행 없이 조용히 끝난다 — 늦은 워커가 오류 로그나 두 번째 행을 만들지 않는다."""
    import types
    from queue import Queue

    import prober

    factory, _ = env
    events = [
        types.SimpleNamespace(type="response.output_text.delta", delta="late", response=None),
        types.SimpleNamespace(type="response.completed", delta=None, response=types.SimpleNamespace(
            usage=types.SimpleNamespace(input_tokens=3, output_tokens=1),
            status="completed", incomplete_details=None)),
    ]
    client = types.SimpleNamespace(responses=types.SimpleNamespace(create=lambda **kw: iter(events)))
    monkeypatch.setenv("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1")
    monkeypatch.setattr(prober, "_get_openai_client", lambda base_url: client)

    slot = worker._ProbeSlot(HUNG, "OpenAI GPT 5.6 Sol (us-east-1)")
    assert slot.begin() and slot.abandon()
    raw = factory()
    q: Queue = Queue()
    prober._probe_single_model(None, HUNG, slot.model_name, "hi", 0.1, 64, 1, q, 1,
                               worker._SlotSession(raw, slot), "chat-short")
    raw.close()
    assert _rows(factory) == []
    kinds = []
    while not q.empty():
        kinds.append(q.get_nowait().split("\n", 1)[0])
    assert "event: result" in kinds and "event: error" not in kinds


def test_future_timeout_leaves_headroom_over_the_wall_clock_cap():
    import prober

    assert worker.PROBE_FUTURE_TIMEOUT_S >= prober.PROBE_WALL_CLOCK_S + 30
    assert worker.PROBE_FUTURE_TIMEOUT_S >= 120
    # 사이클 상한은 running 예약 만료(900s)보다 작아야 다음 스케줄이 겹쳐 돌지 않는다.
    assert worker.CYCLE_DEADLINE_SECONDS < worker.RUNNING_TIMEOUT_SECONDS
