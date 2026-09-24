"""Claude Platform on AWS channels on a 10-minute cadence with their own rotation (v2.29.0).

User request 2026-09-23: only the CP channels (anthropic:*, the Anthropic 1P API) move from the 5-minute
AutoProber cadence to 10 minutes; Bedrock Claude, Nova and OpenAI stay at 5 minutes. The decision is
DB-based: a CP channel is due when the run holding its latest automatic row started at least
(interval - CP_DUE_TOLERANCE_SECONDS) before the current run. CP channels rotate the six workload
categories on their own, so every category is still covered (about once an hour).

All records live in a file-backed SQLite DB; the provider boundary is a fake that writes rows.
"""

import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import auto_prober as worker
import models
import probe_cadence

T0 = datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)
BEDROCK = "global.anthropic.claude-sonnet-5"
OPENAI = "openai:us-east-1:openai.gpt-5.4"
CP_A = "anthropic:claude-sonnet-5"
CP_B = "anthropic:claude-opus-5"
CATALOG = {
    BEDROCK: "Bedrock Claude Sonnet 5 (Global)",
    CP_A: "Anthropic Claude Sonnet 5 (US)",
    CP_B: "Anthropic Claude Opus 5 (US)",
    OPENAI: "OpenAI GPT 5.4 (us-east-1)",
}
PRESET_IDS = [p["id"] for p in worker.WORKLOAD_PRESETS]


class Clock:
    now = T0
    cp_row_offset = 90  # seconds after run start at which CP rows are written


class FakeDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return Clock.now if tz else Clock.now.replace(tzinfo=None)


@pytest.fixture()
def env(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cadence.db'}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    calls = []
    lock = threading.Lock()

    def fake_probe(client, model_id, model_name, prompt, temperature,
                   max_tokens, iteration, event_queue, run_id, db, category=None):
        # CP rows land well into the cycle (after the Bedrock models), like production.
        offset = Clock.cp_row_offset if model_id.startswith("anthropic:") else 10
        row = models.ProbeResult(
            run_id=run_id, model_id=model_id, model_name=model_name, prompt=prompt,
            timestamp=Clock.now + timedelta(seconds=offset), status="success",
            category=category, iteration=1, ttft_ms=10.0,
        )
        db.add(row)
        db.commit()
        with lock:
            calls.append((run_id, model_id, category, prompt, max_tokens))

    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "datetime", FakeDateTime)
    monkeypatch.setattr(worker, "AVAILABLE_MODELS", dict(CATALOG))
    monkeypatch.setattr(worker, "_get_bedrock_client", lambda region: object())
    monkeypatch.setattr(worker, "_get_region_for_model", lambda mid: "us-east-1")
    monkeypatch.setattr(worker, "_probe_single_model", fake_probe)
    monkeypatch.setattr(worker, "_CYCLE_POLL_SECONDS", 0.01)
    monkeypatch.setattr(worker.auto_prober, "current_cycle_running", False)
    monkeypatch.setattr(probe_cadence, "ANTHROPIC_CP_PROBE_INTERVAL_S", 600)
    monkeypatch.setenv("RETENTION_DAYS", "0")
    Clock.now = T0
    Clock.cp_row_offset = 90
    yield factory, calls
    engine.dispose()


def cycle_at(seconds: float) -> int:
    Clock.now = T0 + timedelta(seconds=seconds)
    return worker.run_cycle()


def probed(calls, run_id):
    return {model_id: category for rid, model_id, category, _, _ in calls if rid == run_id}


def test_cp_channels_run_every_other_cycle_and_others_every_cycle(env):
    _, calls = env
    runs = [cycle_at(300 * i) for i in range(6)]

    for index, run_id in enumerate(runs):
        seen = probed(calls, run_id)
        assert BEDROCK in seen and OPENAI in seen  # 5-minute channels: every cycle
        assert (CP_A in seen, CP_B in seen) == ((index % 2 == 0),) * 2  # CP: cycles 0, 2, 4


def test_non_cp_round_robin_is_unchanged_by_the_cp_rotation(env):
    _, calls = env
    runs = [cycle_at(300 * i) for i in range(8)]

    # Same sequence as before v2.29.0: one category step per cycle, wrapping after six.
    assert [probed(calls, run_id)[BEDROCK] for run_id in runs] == [PRESET_IDS[i % 6] for i in range(8)]
    assert [probed(calls, run_id)[OPENAI] for run_id in runs] == [PRESET_IDS[i % 6] for i in range(8)]


def test_cp_rotation_covers_every_category_at_the_slower_cadence(env):
    _, calls = env
    runs = [cycle_at(300 * i) for i in range(12)]  # one hour

    cp_categories = [probed(calls, run_id).get(CP_A) for run_id in runs]
    due = [c for c in cp_categories if c is not None]
    assert due == PRESET_IDS  # six CP probes in an hour, one per category, in order
    assert cp_categories[1::2] == [None] * 6


def test_cp_probe_uses_its_own_prompt_and_max_tokens(env):
    _, calls = env
    cycle_at(0)
    cycle_at(300)
    run_id = cycle_at(600)  # cycle category = code-gen, CP category = reasoning

    by_model = {model_id: (category, prompt, max_tokens) for rid, model_id, category, prompt, max_tokens in calls
                if rid == run_id}
    code_gen, reasoning = worker.WORKLOAD_PRESETS[2], worker.WORKLOAD_PRESETS[1]
    assert by_model[BEDROCK] == ("code-gen", code_gen["prompt"], code_gen["max_tokens"])
    assert by_model[CP_A] == ("reasoning", reasoning["prompt"], reasoning["max_tokens"])
    # The run row keeps the cycle preset (non-CP models).
    factory, _ = env
    with factory() as db:
        run = db.get(models.ProbeRun, run_id)
        assert (run.prompt, run.max_tokens) == (code_gen["prompt"], code_gen["max_tokens"])


@pytest.mark.parametrize("second_cycle, due", [
    (300, False),   # one cycle later — never due
    (449, False),   # just inside the tolerance window
    (450, True),    # interval - tolerance (600 - 150)
    (530, True),    # scheduler jitter: two cycles 70 s early is still due
    (600, True),
    (900, True),    # a skipped cycle — due at the next one
])
def test_due_decision_uses_run_start_times_with_half_cycle_tolerance(env, second_cycle, due):
    _, calls = env
    cycle_at(0)
    run_id = cycle_at(second_cycle)
    assert (CP_A in probed(calls, run_id)) is due


def test_late_cp_rows_do_not_push_the_cadence_to_fifteen_minutes(env):
    """CP rows can land minutes into a slow cycle; judged by row time, 600 s would look like 400 s."""
    _, calls = env
    Clock.cp_row_offset = 200
    cycle_at(0)
    cycle_at(300)
    run_id = cycle_at(600)
    assert CP_A in probed(calls, run_id)


def test_newly_discovered_cp_channel_is_due_immediately_and_starts_from_cycle_category(env, monkeypatch):
    _, calls = env
    cycle_at(0)
    cp_new = "anthropic:claude-haiku-4-5"
    monkeypatch.setattr(worker, "AVAILABLE_MODELS", {**CATALOG, cp_new: "Anthropic Claude Haiku 4.5 (US)"})
    run_id = cycle_at(300)

    seen = probed(calls, run_id)
    assert CP_A not in seen  # probed 300 s ago
    assert seen[cp_new] == seen[BEDROCK] == PRESET_IDS[1]


def test_old_history_restarts_from_the_cycle_category(env):
    _, calls = env
    cycle_at(0)
    run_id = cycle_at(2 * 3600)  # beyond the one-hour history lookback
    seen = probed(calls, run_id)
    assert seen[CP_A] == seen[BEDROCK]


def test_interval_equal_to_the_cycle_probes_cp_every_cycle(env, monkeypatch):
    _, calls = env
    monkeypatch.setattr(probe_cadence, "ANTHROPIC_CP_PROBE_INTERVAL_S", 300)
    runs = [cycle_at(300 * i) for i in range(3)]
    assert all(CP_A in probed(calls, run_id) for run_id in runs)


def test_history_lookup_failure_still_probes_cp_with_the_cycle_preset(env, monkeypatch):
    _, calls = env
    cycle_at(0)

    def broken(run_id):
        raise RuntimeError("simulated DB error")

    monkeypatch.setattr(worker, "_cp_history", broken)
    run_id = cycle_at(300)
    seen = probed(calls, run_id)
    assert seen[CP_A] == seen[BEDROCK] == PRESET_IDS[1]


def test_rows_of_failed_and_manual_runs(env):
    """A failed auto run's CP rows count (they were real calls); manual runs (is_auto=0) do not."""
    factory, calls = env
    with factory() as db:
        failed = models.ProbeRun(prompt="p", status="failed", is_auto=1, created_at=T0)
        manual = models.ProbeRun(prompt="p", status="completed", is_auto=0, created_at=T0)
        db.add_all([failed, manual])
        db.flush()
        db.add(models.ProbeResult(run_id=failed.id, model_id=CP_A, model_name=CATALOG[CP_A], prompt="p",
                                  timestamp=T0 + timedelta(seconds=90), status="error", category="summarize"))
        db.add(models.ProbeResult(run_id=manual.id, model_id=CP_B, model_name=CATALOG[CP_B], prompt="p",
                                  timestamp=T0 + timedelta(seconds=90), status="success", category="summarize"))
        db.commit()

    run_id = cycle_at(300)
    seen = probed(calls, run_id)
    assert CP_A not in seen  # failed auto run 300 s ago holds its latest call
    assert seen[CP_B] == seen[BEDROCK]  # manual probe ignored — due, cycle category


def test_cycle_round_robin_ignores_a_newer_cp_row(env):
    factory, _ = env
    cycle_at(0)  # chat-short for everyone
    with factory() as db:
        run = models.ProbeRun(prompt="p", status="completed", is_auto=1, created_at=T0 + timedelta(seconds=10))
        db.add(run)
        db.flush()
        db.add(models.ProbeResult(run_id=run.id, model_id=CP_A, model_name=CATALOG[CP_A], prompt="p",
                                  timestamp=T0 + timedelta(seconds=20), status="success", category="translate"))
        db.commit()
    assert worker._next_preset()["id"] == PRESET_IDS[1]  # after chat-short, not after translate


def test_hung_cp_probe_timeout_row_keeps_the_cp_category(env, monkeypatch):
    factory, _ = env
    cycle_at(0)
    cycle_at(300)
    release = threading.Event()

    def hanging_probe(client, model_id, model_name, prompt, temperature,
                      max_tokens, iteration, event_queue, run_id, db, category=None):
        if model_id == CP_A:
            release.wait(5)
            return
        db.add(models.ProbeResult(run_id=run_id, model_id=model_id, model_name=model_name, prompt=prompt,
                                  timestamp=Clock.now, status="success", category=category))
        db.commit()

    monkeypatch.setattr(worker, "_probe_single_model", hanging_probe)
    monkeypatch.setattr(worker, "PROBE_FUTURE_TIMEOUT_S", 0.2)
    try:
        run_id = cycle_at(600)
    finally:
        release.set()
    with factory() as db:
        row = db.query(models.ProbeResult).filter_by(run_id=run_id, model_id=CP_A).one()
        assert row.status == "error" and "cycle timeout" in row.error_message
        assert row.category == "reasoning"  # CP rotation, not the cycle's code-gen
        assert row.prompt == worker.WORKLOAD_PRESETS[1]["prompt"]


@pytest.mark.parametrize("raw, expected", [
    (None, 600), ("", 600), ("600", 600), ("900", 900), ("300", 300), ("120", 300), ("abc", 600),
])
def test_interval_env_parsing(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("ANTHROPIC_CP_PROBE_INTERVAL_S", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_CP_PROBE_INTERVAL_S", raw)
    assert probe_cadence._cp_interval_from_env() == expected


def test_interval_for_only_slows_claude_platform_channels(monkeypatch):
    monkeypatch.setattr(probe_cadence, "ANTHROPIC_CP_PROBE_INTERVAL_S", 600)
    assert probe_cadence.interval_for(CP_A) == 600
    for model_id in (BEDROCK, "us.anthropic.claude-haiku-4-5-20251001-v1:0", "us.amazon.nova-2-lite-v1:0", OPENAI):
        assert probe_cadence.interval_for(model_id) == 300
    assert probe_cadence.channel_intervals() == {"anthropic": 600}
