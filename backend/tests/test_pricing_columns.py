"""price_history 표시 전용 단가 열 7개 (v2.31.0) — ensure_price_columns, lifespan 훅 위치."""

import pathlib
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, insert, inspect, select, text
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
SEED_CALL = "ensure_seed(engine, active_channels(AVAILABLE_MODELS, hidden_patterns()))"


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


def test_lifespan_adds_price_columns_in_its_own_block_right_before_the_seed_block():
    columns = MAIN_SRC.index(COLUMNS_CALL)
    seed = MAIN_SRC.index(SEED_CALL)
    repair = MAIN_SRC.index("repair_model_labels(engine, AVAILABLE_MODELS)")
    assert repair < columns < seed < re.search(r"^\s{4}yield$", MAIN_SRC, re.M).start()
    start = MAIN_SRC.rindex("    try:\n", 0, columns)
    handler = MAIN_SRC.index("    except Exception:\n", columns)
    block = MAIN_SRC[start:handler]
    assert "from pricing_seed import ensure_price_columns" in block and "ensure_seed" not in block
    assert MAIN_SRC[handler:].splitlines()[1].strip() == (
        'logger.exception("Price column migration failed (non-fatal, backend continues)")')
    assert MAIN_SRC.index("    try:\n", handler) == MAIN_SRC.rindex("    try:\n", 0, seed)  # the seed block is next
