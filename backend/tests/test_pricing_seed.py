"""단가 seed (v2.30.0, ADR-030) — 55채널 공식 단가, 교정 11채널(결정 8), model_id 단위 멱등, lifespan 훅 위치."""

import logging
import pathlib
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from pricing_seed import CP_SEED, SEED, SEED_SOURCE_DATE, ensure_seed, seed_rows
from pricing_sources import (
    ANTHROPIC_SOURCE_ID, EPOCH, NOVA_USAGETYPES, PriceIdentity, active_channels, price_identity, pricelist_source_id,
)
from tests.pricing_catalog import ACTIVE_MODELS, HIDDEN_1P_MODELS

MAIN_SRC = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
SEED_CALL = "ensure_seed(engine, active_channels(AVAILABLE_MODELS, hidden_patterns()))"
ACTIVE = {mid: price_identity(mid) for mid in ACTIVE_MODELS}

CORRECTED = {  # v2.29.1 값이 처음부터 틀린 11채널(US는 Global 값, Nova는 1세대 Nova Lite 값)
    "us.anthropic.claude-fable-5-1": (11.0, 55.0), "us.anthropic.claude-fable-5": (11.0, 55.0),
    "us.anthropic.claude-opus-5-5": (4.4, 22.0), "us.anthropic.claude-opus-5": (5.5, 27.5),
    "us.anthropic.claude-opus-4-8": (5.5, 27.5), "us.anthropic.claude-opus-4-7": (5.5, 27.5),
    "us.anthropic.claude-opus-4-6-v1": (5.5, 27.5), "us.anthropic.claude-sonnet-5": (2.2, 11.0),
    "us.anthropic.claude-sonnet-4-6": (3.3, 16.5), "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.1, 5.5),
    "us.amazon.nova-2-lite-v1:0": (0.33, 2.75),
}
STANDARD = {  # Anthropic 표준 단가 = Bedrock Global = CP (family_key 기준, Opus 4.6은 CP 없음)
    "claude-fable-5-1": (10.0, 50.0), "claude-fable-5": (10.0, 50.0), "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0), "claude-opus-4-8": (5.0, 25.0), "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0), "claude-sonnet-5": (2.0, 10.0), "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
OPENAI = {  # family_key → (US CRIS와 in-region, Global CRIS)
    "gpt-6-astra": ((11.0, 55.0), (10.0, 50.0)), "gpt-6-sol": ((2.2, 11.0), (2.0, 10.0)),
    "gpt-6-luna": ((0.11, 0.55), (0.1, 0.5)), "gpt-5.6-sol": ((4.4, 22.0), (4.0, 20.0)),
    "gpt-5.6-terra": ((2.2, 13.2), (2.0, 12.0)), "gpt-5.6-luna": ((0.22, 1.32), (0.2, 1.2)),
    "gpt-5.5": ((5.5, 33.0), None), "gpt-5.4": ((2.75, 16.5), None),
}


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(eng)
    return eng


def _rows(eng):
    with sessionmaker(bind=eng)() as s:
        return {r.model_id: r for r in s.execute(select(models.PriceHistory)).scalars()}


def _utc(dt):  # SQLite는 DateTime(timezone=True)를 naive로 돌려준다
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _add(eng, **row):
    with sessionmaker(bind=eng)() as s:
        s.add(models.PriceHistory(**row))
        s.commit()


def test_seed_covers_every_active_channel():
    assert len(SEED) == 46
    assert set(SEED) == {m for m, i in ACTIVE.items() if i.channel != "cp"}
    assert set(CP_SEED) == {i.family_key for i in ACTIVE.values() if i.channel == "cp"}
    rows = seed_rows(ACTIVE)
    assert set(rows) == set(ACTIVE)
    assert rows["anthropic:claude-haiku-4-5-20251001"] == (1.0, 5.0, ANTHROPIC_SOURCE_ID)  # CP 날짜 접미사 id
    assert SEED_SOURCE_DATE.isoformat() == "2026-09-26"


@pytest.mark.parametrize("model_id", sorted(CORRECTED))
def test_corrected_eleven_channels(model_id):
    assert SEED[model_id][:2] == CORRECTED[model_id]


def test_values_per_channel():
    for mid, ident in ACTIVE.items():
        inp, out, src = seed_rows(ACTIVE)[mid]
        assert isinstance(inp, float) and isinstance(out, float), mid
        if ident.channel in ("cp", "global") and ident.provider == "anthropic":
            assert (inp, out) == STANDARD[ident.family_key], mid
        elif ident.channel == "us" and ident.provider == "anthropic":
            g_in, g_out = STANDARD[ident.family_key]
            assert (inp, out) == (round(g_in * 1.1, 6), round(g_out * 1.1, 6)), mid
        elif ident.provider == "openai":
            regional, global_ = OPENAI[ident.family_key]
            assert (inp, out) == (global_ if ident.channel == "global" else regional), mid
    assert {src for _, _, src in CP_SEED.values()} == {ANTHROPIC_SOURCE_ID}


def test_seed_source_ids_follow_the_price_identity():
    by_fm: dict[str, set[str]] = {}
    for mid, (_, _, src) in SEED.items():
        ident = ACTIVE[mid]
        if ident.source_kind == "offer":
            assert re.fullmatch(r"offer:offer-[a-z0-9]{13}", src), (mid, src)
            by_fm.setdefault(ident.source_ref, set()).add(src)
        else:
            assert src == pricelist_source_id(NOVA_USAGETYPES[ident.source_ref][0])
    assert len(by_fm) == 18 and all(len(v) == 1 for v in by_fm.values())  # FM당 오퍼 1개를 모든 채널이 인용
    assert len(set().union(*by_fm.values())) == 18
    assert by_fm["anthropic.claude-opus-5-5"] == {"offer:offer-7sp77cpl4rveu"}
    assert by_fm["openai.gpt-5.4"] == {"offer:offer-5l5a5izq5fbec"}
    assert by_fm["openai.gpt-6-astra"] == {"offer:offer-7epta7rbw5aws"}


def test_seed_rows_skip_active_ids_without_seed(caplog):
    new = PriceIdentity("claude-opus-9", "Claude Opus 9", "anthropic", "global", "offer", "anthropic.claude-opus-9")
    with caplog.at_level(logging.WARNING, logger="pricing_seed"):
        rows = seed_rows({"global.anthropic.claude-opus-9": new,
                          "global.anthropic.claude-opus-5": ACTIVE["global.anthropic.claude-opus-5"]})
    assert list(rows) == ["global.anthropic.claude-opus-5"]
    assert "global.anthropic.claude-opus-9" in caplog.text


def test_ensure_seed_inserts_every_active_channel_then_is_idempotent(engine):
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    assert ensure_seed(engine, ACTIVE) == 55
    assert not any("pg_advisory" in s for s in statements)  # SQLite는 잠금 생략
    rows = _rows(engine)
    assert set(rows) == set(ACTIVE)
    for mid, row in rows.items():
        assert (row.input_per_mtok, row.output_per_mtok, row.source_id) == seed_rows(ACTIVE)[mid]
        assert (row.family_key, row.channel) == (ACTIVE[mid].family_key, ACTIVE[mid].channel)
        assert (row.status, row.observed_at, row.run_id) == ("seed", None, None)
        assert _utc(row.effective_from) == EPOCH and row.created_at is not None
    assert ensure_seed(engine, ACTIVE) == 0
    assert len(_rows(engine)) == 55


def test_existing_row_blocks_seeding_only_that_model_id(engine):
    _add(engine, model_id="us.amazon.nova-2-lite-v1:0", family_key="nova-2-lite", channel="us",
         input_per_mtok=0.06, output_per_mtok=0.24, effective_from=EPOCH, status="rejected",
         source_id="pricelist:USE1-Nova2.0Lite-input-tokens", observed_at=datetime(2026, 9, 26, 3, tzinfo=timezone.utc))
    assert ensure_seed(engine, ACTIVE) == 54
    rows = _rows(engine)
    assert (rows["us.amazon.nova-2-lite-v1:0"].status, rows["us.amazon.nova-2-lite-v1:0"].input_per_mtok) == ("rejected", 0.06)
    assert sum(r.status == "seed" for r in rows.values()) == 54


def test_sync_first_then_seed_still_fills_the_rest(engine):
    started = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)
    with sessionmaker(bind=engine)() as s:
        run = models.PriceSyncRun(started_at=started, status="completed")
        s.add(run)
        s.commit()
        run_id = run.id
    _add(engine, model_id="us.anthropic.claude-opus-5-5", family_key="claude-opus-5-5", channel="us",
         input_per_mtok=4.4, output_per_mtok=22.0, effective_from=started, status="verified",
         source_id="offer:offer-7sp77cpl4rveu", observed_at=started, run_id=run_id)
    assert ensure_seed(engine, active_channels({**ACTIVE_MODELS, **HIDDEN_1P_MODELS}, ["(1P)"])) == 54
    rows = _rows(engine)
    assert set(rows) == set(ACTIVE)
    assert rows["us.anthropic.claude-opus-5-5"].status == "verified"
    assert _utc(rows["us.anthropic.claude-opus-5-5"].effective_from) == started
    assert rows["global.anthropic.claude-opus-5-5"].status == "seed"


def test_ensure_seed_postgres_takes_transaction_advisory_lock_first():
    log: list[str] = []
    conn = SimpleNamespace(execute=lambda stmt, params=None: log.append(str(stmt)) or SimpleNamespace(scalars=lambda: iter(())))

    class _Begin:
        def __enter__(self):
            return conn

        def __exit__(self, *exc):
            return False

    pg = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), begin=_Begin)
    assert ensure_seed(pg, {"us.amazon.nova-2-lite-v1:0": ACTIVE["us.amazon.nova-2-lite-v1:0"]}) == 1
    assert log[0] == "SELECT pg_advisory_xact_lock(917350003)"
    assert log[1].startswith("SELECT DISTINCT price_history.model_id")
    assert log[2].startswith("INSERT INTO price_history") and len(log) == 3
    assert ensure_seed(SimpleNamespace(dialect=pg.dialect, begin=None), {}) == 0  # 빈 활성 집합은 DB를 건드리지 않는다


def test_lifespan_seeds_after_migration_and_registration_non_fatal():
    unlock = MAIN_SRC.index("SELECT pg_advisory_unlock(917350001)")
    register = re.search(r"^\s+_register_openai_models\(\)$", MAIN_SRC, re.M).start()
    seed = MAIN_SRC.index(SEED_CALL)
    assert unlock < register < seed < re.search(r"^\s{4}yield$", MAIN_SRC, re.M).start()
    block = MAIN_SRC[MAIN_SRC.rindex("    try:\n", 0, seed):MAIN_SRC.index("    except Exception:\n", seed)]
    assert "from pricing_seed import ensure_seed" in block and "yield" not in block
    after = MAIN_SRC[MAIN_SRC.index("    except Exception:\n", seed):].splitlines()[1].strip()
    assert after.startswith('logger.exception("Price seed failed')
