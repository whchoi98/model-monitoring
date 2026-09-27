"""price_history 표시 전용 단가 열 7개 (v2.31.0) — ensure_price_columns, lifespan 훅 위치, 실패 시 백그라운드 재시도."""

import logging
import pathlib
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, insert, inspect, select, text
from sqlalchemy.exc import NoSuchTableError, OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
import models
import pricing_seed
from pricing_seed import ensure_price_columns
from pricing_sources import EPOCH

NEW_COLUMNS = [
    "cache_read_per_mtok", "cache_write_per_mtok", "cache_write_1h_per_mtok", "long_input_per_mtok",
    "long_output_per_mtok", "long_cache_read_per_mtok", "long_cache_write_per_mtok",
]
V230_COLUMNS = [
    "id", "model_id", "family_key", "channel", "input_per_mtok", "output_per_mtok", "effective_from",
    "source_id", "status", "observed_at", "run_id", "created_at",
]
# v2.30.0 create_all이 SQLite에 만든 price_history 그대로(새 열 없음)
V230_DDL = (
    "CREATE TABLE price_history (id INTEGER NOT NULL, model_id TEXT NOT NULL, family_key TEXT NOT NULL, "
    "channel TEXT NOT NULL, input_per_mtok FLOAT NOT NULL, output_per_mtok FLOAT NOT NULL, "
    "effective_from DATETIME NOT NULL, source_id TEXT NOT NULL, status TEXT NOT NULL, observed_at DATETIME, "
    "run_id INTEGER, created_at DATETIME, PRIMARY KEY (id))"
)
MAIN_SRC = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
COLUMNS_CALL = "ensure_price_columns(engine)"
SEED_CALL = "ensure_seed(engine, active)"
PRICE_SCHEMA_CALL = "    _ensure_price_schema()\n"  # the lifespan call (the def line has no bare newline after "()")


def _engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


@pytest.fixture()
def v230():
    """A v2.30.0 database: price_history without the seven columns and one seed row in it."""
    eng = _engine()
    with eng.begin() as conn:
        conn.execute(text(V230_DDL))
        conn.execute(text("CREATE INDEX ix_price_history_model_eff ON price_history (model_id, effective_from)"))
        conn.execute(insert(models.PriceHistory.__table__).values(  # v2.30.0 columns only
            model_id="global.anthropic.claude-opus-5-5", family_key="claude-opus-5-5", channel="global",
            input_per_mtok=4.0, output_per_mtok=20.0, effective_from=EPOCH, source_id="offer:offer-7sp77cpl4rveu",
            status="seed"))
    yield eng
    eng.dispose()


def _record(eng) -> list[str]:
    statements: list[str] = []
    event.listen(eng, "before_cursor_execute", lambda *a: statements.append(a[2]))
    return statements


def test_the_orm_declares_the_seven_nullable_float_columns():
    table = models.PriceHistory.__table__
    for name in NEW_COLUMNS:
        column = table.c[name]
        assert column.nullable and column.type.__class__.__name__ == "Float", name


def test_adds_the_seven_columns_to_a_v230_table_then_is_a_no_op(v230):
    statements = _record(v230)
    assert [c["name"] for c in inspect(v230).get_columns("price_history")] == V230_COLUMNS
    assert ensure_price_columns(v230) == NEW_COLUMNS
    assert [s for s in statements if s.startswith("ALTER")] == [
        f"ALTER TABLE price_history ADD COLUMN {name} FLOAT" for name in NEW_COLUMNS]
    columns = {c["name"]: c for c in inspect(v230).get_columns("price_history")}
    assert list(columns) == V230_COLUMNS + NEW_COLUMNS and all(columns[n]["nullable"] for n in NEW_COLUMNS)
    statements.clear()
    assert ensure_price_columns(v230) == []
    assert not [s for s in statements if s.lstrip().upper().startswith(("ALTER", "SET", "CREATE", "UPDATE"))]


def test_the_existing_row_keeps_its_values_and_the_new_columns_round_trip(v230):
    ensure_price_columns(v230)
    Session = sessionmaker(bind=v230)
    with Session() as db:
        row = db.execute(select(models.PriceHistory)).scalar_one()
        assert (row.input_per_mtok, row.output_per_mtok, row.status) == (4.0, 20.0, "seed")
        assert all(getattr(row, name) is None for name in NEW_COLUMNS)
        row.cache_read_per_mtok, row.cache_write_per_mtok = 0.2, 0.0   # an official $0 price stays 0, not NULL
        db.commit()
    with Session() as db:
        row = db.execute(select(models.PriceHistory)).scalar_one()
        assert (row.cache_read_per_mtok, row.cache_write_per_mtok, row.long_input_per_mtok) == (0.2, 0.0, None)


def test_only_the_missing_columns_are_added_in_extra_fields_order(v230):
    with v230.begin() as conn:
        conn.execute(text("ALTER TABLE price_history ADD COLUMN long_input_per_mtok FLOAT"))
        conn.execute(text("ALTER TABLE price_history ADD COLUMN cache_read_per_mtok FLOAT"))
    statements = _record(v230)
    missing = [n for n in NEW_COLUMNS if n not in ("long_input_per_mtok", "cache_read_per_mtok")]
    assert ensure_price_columns(v230) == missing
    assert [s for s in statements if s.startswith("ALTER")] == [
        f"ALTER TABLE price_history ADD COLUMN {name} FLOAT" for name in missing]


def test_a_fresh_create_all_database_needs_no_ddl():
    eng = _engine()
    models.Base.metadata.create_all(eng)
    statements = _record(eng)
    assert ensure_price_columns(eng) == []
    assert not [s for s in statements if s.startswith("ALTER")]
    eng.dispose()


def test_errors_propagate_to_the_caller():
    eng = _engine()  # no price_history table at all
    with pytest.raises(NoSuchTableError):
        ensure_price_columns(eng)
    eng.dispose()


class _Begin:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


def test_postgres_sets_transaction_timeouts_then_adds_if_not_exists(monkeypatch):
    asked: list[str] = []

    def inspector(columns):
        return lambda bind: SimpleNamespace(get_columns=lambda table: asked.append(table) or [{"name": n} for n in columns])

    monkeypatch.setattr(pricing_seed, "sa_inspect", inspector(V230_COLUMNS))
    log: list[str] = []
    conn = SimpleNamespace(execute=lambda stmt, params=None: log.append(str(stmt)))
    pg = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), begin=lambda: _Begin(conn))
    assert ensure_price_columns(pg) == NEW_COLUMNS
    assert asked == ["price_history"]
    assert log == [
        "SET LOCAL statement_timeout = '30000'",
        "SET LOCAL lock_timeout = '5000'",
        *(f"ALTER TABLE price_history ADD COLUMN IF NOT EXISTS {name} DOUBLE PRECISION" for name in NEW_COLUMNS),
    ]
    monkeypatch.setattr(pricing_seed, "sa_inspect", inspector(V230_COLUMNS + NEW_COLUMNS))
    # every column present: no transaction is opened, so no ACCESS EXCLUSIVE lock is requested on every start
    assert ensure_price_columns(SimpleNamespace(dialect=pg.dialect, begin=None)) == []


def _function_src(name: str) -> str:
    start = MAIN_SRC.index(f"\ndef {name}(")
    return MAIN_SRC[start:MAIN_SRC.index("\ndef ", start + 1)]


def test_lifespan_adds_price_columns_in_its_own_block_right_before_the_seed_block():
    repair = MAIN_SRC.index("repair_model_labels(engine, AVAILABLE_MODELS)")
    call = MAIN_SRC.index(PRICE_SCHEMA_CALL)
    assert repair < call < re.search(r"^\s{4}yield$", MAIN_SRC, re.M).start()
    fn = _function_src("_ensure_price_schema")
    columns, seed = fn.index(COLUMNS_CALL), fn.index(SEED_CALL)
    assert columns < seed
    start = fn.rindex("    try:\n", 0, columns)
    handler = fn.index("    except Exception:\n", columns)
    block = fn[start:handler]
    assert "from pricing_seed import ensure_price_columns" in block and "ensure_seed" not in block
    assert [line.strip() for line in fn[handler:].splitlines()[1:3]] == [
        "failed = True", 'logger.exception("Price column migration failed (non-fatal, backend continues)")']
    assert fn.index("    try:\n", handler) == fn.rindex("    try:\n", 0, seed)  # the seed block is next


# ── 실패 시 백그라운드 재시도 (lifespan은 기다리지 않는다) ──

def _lock_timeout() -> OperationalError:
    return OperationalError("ALTER TABLE price_history", {}, Exception("canceling statement due to lock timeout"))


class _Recorder:
    """Stands in for ensure_price_columns or ensure_seed: raises the queued errors in turn, then succeeds."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls: list[tuple] = []

    def __call__(self, *args):
        self.calls.append(args)
        if self.errors:
            raise self.errors.pop(0)
        return []


class _FakeThread:
    created: list["_FakeThread"] = []

    def __init__(self, target=None, args=(), name=None, daemon=None):
        self.target, self.args, self.name, self.daemon, self.started = target, args, name, daemon, False
        _FakeThread.created.append(self)

    def start(self):
        self.started = True


@pytest.fixture()
def schema(monkeypatch):
    """_ensure_price_schema and _retry_price_schema with the two functions, Thread and the sleep replaced."""
    columns, seed, slept = _Recorder(), _Recorder(), []
    monkeypatch.setattr(pricing_seed, "ensure_price_columns", columns)
    monkeypatch.setattr(pricing_seed, "ensure_seed", seed)
    monkeypatch.setattr(main.threading, "Thread", _FakeThread)
    monkeypatch.setattr(main.time, "sleep", slept.append)
    _FakeThread.created = []
    return SimpleNamespace(columns=columns, seed=seed, slept=slept, threads=_FakeThread.created)


def test_the_retry_defaults_are_three_attempts_thirty_seconds_apart():
    assert (main.PRICE_SCHEMA_RETRY_ATTEMPTS, main.PRICE_SCHEMA_RETRY_INTERVAL_S) == (3, 30)


def test_a_first_attempt_success_starts_no_thread(schema):
    from pricing_sources import active_channels
    from prober import AVAILABLE_MODELS
    from visibility import hidden_patterns

    assert main._ensure_price_schema() is None
    assert schema.threads == [] and schema.slept == []
    assert schema.columns.calls == [(main.engine,)]
    ((engine, active),) = schema.seed.calls
    assert engine is main.engine and active == active_channels(AVAILABLE_MODELS, hidden_patterns())


@pytest.mark.parametrize("failing", ["columns", "seed"])
def test_a_startup_failure_starts_the_retry_thread_without_waiting(schema, failing, caplog):
    getattr(schema, failing).errors.append(_lock_timeout())
    with caplog.at_level(logging.ERROR, logger="main"):
        thread = main._ensure_price_schema()
    assert schema.threads == [thread] and thread.started
    assert (thread.target, thread.name, thread.daemon) == (main._retry_price_schema, "price-schema-retry", True)
    ((_, active),) = schema.seed.calls  # the seed still runs after a column failure
    assert thread.args == (active,) and thread.args[0] is active
    assert schema.slept == []  # startup never sleeps: the retries run in the thread
    message = {"columns": "Price column migration failed", "seed": "Price seed failed"}[failing]
    assert [r.getMessage() for r in caplog.records] == [f"{message} (non-fatal, backend continues)"]


def test_the_retry_reruns_both_steps_with_the_same_active_set_and_stops_at_the_first_success(schema, monkeypatch,
                                                                                            caplog):
    monkeypatch.setattr(main, "PRICE_SCHEMA_RETRY_INTERVAL_S", 0.5)
    schema.columns.errors.append(_lock_timeout())
    active = {"global.anthropic.claude-opus-5-5": object()}
    with caplog.at_level(logging.INFO, logger="main"):
        assert main._retry_price_schema(active) is True
    assert schema.slept == [0.5, 0.5]  # waits before each attempt, the second attempt succeeds
    assert schema.columns.calls == [(main.engine,)] * 2
    ((engine, seeded),) = schema.seed.calls  # the seed never runs after a failed column step
    assert engine is main.engine and seeded is active
    records = [r for r in caplog.records if r.name == "main"]
    assert [(r.levelno, r.getMessage()) for r in records] == [
        (logging.ERROR, "Price schema retry 1/3 failed"), (logging.INFO, "Price schema retry 2/3 succeeded")]
    assert records[0].exc_info is not None  # logger.exception keeps the traceback


def test_a_seed_failure_is_retried_too(schema, monkeypatch):
    monkeypatch.setattr(main, "PRICE_SCHEMA_RETRY_INTERVAL_S", 0)
    schema.seed.errors.append(RuntimeError("seed failed"))
    assert main._retry_price_schema({}) is True
    assert len(schema.columns.calls) == 2 and len(schema.seed.calls) == 2 and schema.slept == [0, 0]


def test_the_retry_gives_up_after_the_last_attempt(schema, monkeypatch, caplog):
    monkeypatch.setattr(main, "PRICE_SCHEMA_RETRY_ATTEMPTS", 2)
    schema.columns.errors.extend([_lock_timeout(), _lock_timeout(), _lock_timeout()])
    with caplog.at_level(logging.INFO, logger="main"):
        assert main._retry_price_schema({}) is False
    assert schema.slept == [30, 30] and len(schema.columns.calls) == 2 and schema.seed.calls == []
    records = [r for r in caplog.records if r.name == "main"]
    assert [r.getMessage() for r in records[:2]] == ["Price schema retry 1/2 failed", "Price schema retry 2/2 failed"]
    assert all(r.exc_info is not None for r in records[:2])
    assert records[2].levelno == logging.ERROR and records[2].getMessage().startswith("Price schema retries exhausted")
