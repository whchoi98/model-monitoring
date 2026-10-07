"""단가 seed (v2.30.0, ADR-030) — 55채널 공식 단가, 교정 11채널(결정 8), model_id 단위 멱등, lifespan 훅 위치.
v2.31.0: OpenAI 공식 가격 8채널(openai-list:<family_key>)은 OPENAI_LIST_SEED(family_key 단위)로 푼다."""

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
from pricing_parsers import parse_openai_pricing_md
from pricing_seed import (
    CP_SEED, OPENAI_LIST_SEED, SEED, SEED_SOURCE_DATE, SEED_SOURCE_DATES, ensure_seed, seed_extra, seed_rows,
)
from pricing_sources import (
    ANTHROPIC_SOURCE_ID, EPOCH, NOVA_USAGETYPES, OPENAI_SOURCE_ID, PriceIdentity, active_channels, price_identity,
    pricelist_source_id, tier_of,
)
from tests.pricing_catalog import ACTIVE_MODELS, HIDDEN_1P_MODELS, OPENAI_LIST_IDS

MAIN_SRC = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
SEED_CALL = "ensure_seed(engine, active)"
PRICE_SCHEMA_CALL = "    _ensure_price_schema()\n"  # the lifespan call (the def line has no bare newline after "()")
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
    "claude-opus-4-6": (5.0, 25.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0), "claude-haiku-5-5": (0.1, 0.5), "claude-haiku-4-5": (1.0, 5.0),
}
OPENAI = {  # family_key → (US CRIS와 in-region, Global CRIS)
    "gpt-6.1-sol": ((2.2, 11.0), (2.0, 10.0)),
    "gpt-6-astra": ((11.0, 55.0), (10.0, 50.0)), "gpt-6-sol": ((2.2, 11.0), (2.0, 10.0)),
    "gpt-6-luna": ((0.11, 0.55), (0.1, 0.5)), "gpt-5.6-sol": ((4.4, 22.0), (4.0, 20.0)),
    "gpt-5.6-terra": ((2.2, 13.2), (2.0, 12.0)), "gpt-5.6-luna": ((0.22, 1.32), (0.2, 1.2)),
    "gpt-5.5": ((5.5, 33.0), None), "gpt-5.4": ((2.75, 16.5), None),
}
OPENAI_LIST = {  # OpenAI 공식 가격(Standard, 짧은 컨텍스트) — OpenAI pricing.md 2026-09-27
    "gpt-6.1-sol": (2.0, 10.0),
    "gpt-6-astra": (10.0, 50.0), "gpt-6-sol": (2.0, 10.0), "gpt-6-luna": (0.1, 0.5), "gpt-5.6-sol": (4.0, 20.0),
    "gpt-5.6-terra": (2.0, 12.0), "gpt-5.6-luna": (0.2, 1.2), "gpt-5.5": (5.0, 30.0), "gpt-5.4": (2.5, 15.0),
}
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "pricing"


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
    assert len(SEED) == 55
    assert set(SEED) == {m for m, i in ACTIVE.items() if i.channel != "cp"}
    assert set(CP_SEED) == {i.family_key for i in ACTIVE.values() if i.channel == "cp"}
    rows = seed_rows(ACTIVE)
    assert set(rows) == set(ACTIVE)
    assert rows["anthropic:claude-haiku-4-5-20251001"] == (1.0, 5.0, ANTHROPIC_SOURCE_ID)  # CP 날짜 접미사 id
    assert SEED_SOURCE_DATE.isoformat() == "2026-09-27"
    assert set(OPENAI_LIST_SEED) == {i.family_key for i in ACTIVE.values() if i.provider == "openai"}


def test_openai_list_seed_is_the_openai_standard_price_per_family():
    assert OPENAI_LIST_SEED == {fk: (i, o, OPENAI_SOURCE_ID) for fk, (i, o) in OPENAI_LIST.items()}
    assert all(isinstance(v, float) for i, o, _ in OPENAI_LIST_SEED.values() for v in (i, o))
    doc = parse_openai_pricing_md((FIXTURES / "openai_pricing.md").read_text(encoding="utf-8"))
    assert {fk: (float(doc[fk].input), float(doc[fk].output)) for fk in OPENAI_LIST} == OPENAI_LIST  # = the doc
    for fk, (i, o) in OPENAI_LIST.items():  # Bedrock Global CRIS = OpenAI price, US CRIS and In Region = +10 %
        regional, global_ = OPENAI[fk]
        assert regional == (round(i * 1.1, 6), round(o * 1.1, 6)), fk
        assert global_ in (None, (i, o)), fk


def test_gpt_us_cris_seed_equals_in_region_on_every_price():
    """The export's fixed note 3 (v2.31.1): GPT US CRIS and In Region prices are the same (one offer dimension,
    input_tokens_standard, for both), extra prices included."""
    rows = seed_rows(ACTIVE)
    by_family: dict[str, dict[str, list[str]]] = {}
    for mid, ident in ACTIVE.items():
        if ident.provider == "openai":
            by_family.setdefault(ident.family_key, {}).setdefault(tier_of(ident.channel), []).append(mid)
    with_us = {fk: tiers for fk, tiers in by_family.items() if "us" in tiers}
    assert set(with_us) == {"gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna"}
    for fk, tiers in with_us.items():
        (us,) = tiers["us"]
        for regional in tiers["in_region"]:
            assert rows[us][:2] == rows[regional][:2], (fk, regional)
            assert seed_extra(us, ACTIVE[us]) == seed_extra(regional, ACTIVE[regional]), (fk, regional)


def test_seed_rows_resolve_openai_list_channels_by_family_key():
    active = active_channels({**ACTIVE_MODELS, **HIDDEN_1P_MODELS}, ["(1P)"])
    rows = seed_rows(active)
    assert set(rows) == set(ACTIVE) | set(OPENAI_LIST_IDS) and len(rows) == 75
    assert rows["openai-list:gpt-5.6-sol"] == (4.0, 20.0, OPENAI_SOURCE_ID)
    assert not any(m in SEED for m in OPENAI_LIST_IDS)  # family_key 표(CP와 같은 방식), model_id 표에는 없다


@pytest.mark.parametrize("model_id", sorted(CORRECTED))
def test_corrected_eleven_channels(model_id):
    assert SEED[model_id][:2] == CORRECTED[model_id]


def test_values_per_channel():
    for mid, ident in ACTIVE.items():
        inp, out, src = seed_rows(ACTIVE)[mid]
        assert isinstance(inp, float) and isinstance(out, float), mid
        if ident.channel in ("cp", "global") and ident.provider == "anthropic":
            assert (inp, out) == STANDARD[ident.family_key], mid
        elif ident.channel != "global" and ident.provider == "anthropic":  # US CRIS, in-region(서울) = Global x 1.1
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
    assert len(by_fm) == 21 and all(len(v) == 1 for v in by_fm.values())  # FM당 오퍼 1개를 모든 채널이 인용
    assert len(set().union(*by_fm.values())) == 21
    assert by_fm["anthropic.claude-opus-5-5"] == {"offer:offer-7sp77cpl4rveu"}
    assert by_fm["openai.gpt-5.4"] == {"offer:offer-5l5a5izq5fbec"}
    assert by_fm["openai.gpt-6-astra"] == {"offer:offer-7epta7rbw5aws"}
    assert by_fm["anthropic.claude-sonnet-5-5"] == {"offer:offer-5fu2rhus3byrs"}
    assert by_fm["openai.gpt-6.1-sol"] == {"offer:offer-wbhj4kycntgkk"}
    assert SEED["bedrock:ap-northeast-2:anthropic.claude-opus-5"][2] == SEED["us.anthropic.claude-opus-5"][2]


def test_seed_rows_skip_active_ids_without_seed(caplog):
    new = PriceIdentity("claude-opus-9", "Claude Opus 9", "anthropic", "global", "offer", "anthropic.claude-opus-9")
    new_list = PriceIdentity("gpt-7", "GPT 7", "openai", "openai_list", "openai_doc", "gpt-7")
    with caplog.at_level(logging.WARNING, logger="pricing_seed"):
        rows = seed_rows({"global.anthropic.claude-opus-9": new, "openai-list:gpt-7": new_list,
                          "global.anthropic.claude-opus-5": ACTIVE["global.anthropic.claude-opus-5"]})
    assert list(rows) == ["global.anthropic.claude-opus-5"]
    assert "global.anthropic.claude-opus-9" in caplog.text and "openai-list:gpt-7" in caplog.text


def test_ensure_seed_inserts_every_active_channel_then_is_idempotent(engine):
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    assert ensure_seed(engine, ACTIVE) == 66
    assert not any("pg_advisory" in s for s in statements)  # SQLite는 잠금 생략
    rows = _rows(engine)
    assert set(rows) == set(ACTIVE)
    for mid, row in rows.items():
        assert (row.input_per_mtok, row.output_per_mtok, row.source_id) == seed_rows(ACTIVE)[mid]
        assert (row.family_key, row.channel) == (ACTIVE[mid].family_key, ACTIVE[mid].channel)
        assert (row.status, row.observed_at, row.run_id) == ("seed", None, None)
        assert _utc(row.effective_from) == EPOCH and row.created_at is not None
    assert ensure_seed(engine, ACTIVE) == 0
    assert len(_rows(engine)) == 66


def test_existing_row_blocks_seeding_only_that_model_id(engine):
    _add(engine, model_id="us.amazon.nova-2-lite-v1:0", family_key="nova-2-lite", channel="us",
         input_per_mtok=0.06, output_per_mtok=0.24, effective_from=EPOCH, status="rejected",
         source_id="pricelist:USE1-Nova2.0Lite-input-tokens", observed_at=datetime(2026, 9, 26, 3, tzinfo=timezone.utc))
    assert ensure_seed(engine, ACTIVE) == 65
    rows = _rows(engine)
    assert (rows["us.amazon.nova-2-lite-v1:0"].status, rows["us.amazon.nova-2-lite-v1:0"].input_per_mtok) == ("rejected", 0.06)
    assert sum(r.status == "seed" for r in rows.values()) == 65


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
    assert ensure_seed(engine, active_channels({**ACTIVE_MODELS, **HIDDEN_1P_MODELS}, ["(1P)"])) == 74
    rows = _rows(engine)
    assert set(rows) == set(ACTIVE) | set(OPENAI_LIST_IDS)  # 66 - 1 already priced + 9 OpenAI official prices
    listed = rows["openai-list:gpt-6-astra"]
    assert (listed.family_key, listed.channel, listed.source_id, listed.status) == (
        "gpt-6-astra", "openai_list", OPENAI_SOURCE_ID, "seed")
    assert (listed.input_per_mtok, listed.output_per_mtok) == (10.0, 50.0)
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
    assert log[:3] == [  # 트랜잭션 한정 상한 두 개, 그다음 잠금
        "SET LOCAL statement_timeout = '30000'",
        "SET LOCAL lock_timeout = '5000'",
        "SELECT pg_advisory_xact_lock(917350003)",
    ]
    assert log[3].startswith("SELECT DISTINCT price_history.model_id")
    assert log[4].startswith("INSERT INTO price_history") and len(log) == 5
    assert ensure_seed(SimpleNamespace(dialect=pg.dialect, begin=None), {}) == 0  # 빈 활성 집합은 DB를 건드리지 않는다


def test_lifespan_seeds_after_migration_and_registration_non_fatal():
    # the migration block ends at its failure handler (no unlock statement since v2.32.2: the transaction-scoped advisory lock
    # is released by the block's commit or rollback)
    migration = MAIN_SRC.index('logger.exception("Migration block failed')
    register = re.search(r"^\s+_register_openai_models\(\)$", MAIN_SRC, re.M).start()
    call = MAIN_SRC.index(PRICE_SCHEMA_CALL)  # the seed runs inside _ensure_price_schema (v2.31.0)
    assert migration < register < call < re.search(r"^\s{4}yield$", MAIN_SRC, re.M).start()
    fn = MAIN_SRC[MAIN_SRC.index("\ndef _ensure_price_schema("):MAIN_SRC.index("\ndef _retry_price_schema(")]
    seed = fn.index(SEED_CALL)
    block = fn[fn.rindex("    try:\n", 0, seed):fn.index("    except Exception:\n", seed)]
    assert "from pricing_seed import ensure_seed" in block and "yield" not in block
    after = [line.strip() for line in fn[fn.index("    except Exception:\n", seed):].splitlines()[1:3]]
    assert after[0] == "failed = True" and after[1].startswith('logger.exception("Price seed failed')


def test_v2_32_new_channels_seed_values():
    """Claude Sonnet 5.5 (Global, CP), GPT 6.1 Sol (Global, US, us-east-1), Seoul in-region Opus 5 / Sonnet 5."""
    rows = seed_rows(ACTIVE)
    assert rows["global.anthropic.claude-sonnet-5-5"] == (2.0, 10.0, "offer:offer-5fu2rhus3byrs")
    # v2.32.0에는 us. 프로파일이 없었다(2026-09-30) — v2.33.0 US 채널은 test_haiku55_catalog.py
    assert rows["anthropic:claude-sonnet-5-5"] == (2.0, 10.0, ANTHROPIC_SOURCE_ID)
    assert rows["bedrock:ap-northeast-2:anthropic.claude-opus-5"] == (5.5, 27.5, "offer:offer-f3u6lgbrem3zs")
    assert rows["bedrock:ap-northeast-2:anthropic.claude-sonnet-5"] == (2.2, 11.0, "offer:offer-2ykemehpsyf7g")
    for mid, want in (("openai:global:global.openai.gpt-6.1-sol", (2.0, 10.0)), ("openai:us:us.openai.gpt-6.1-sol", (2.2, 11.0)),
                      ("openai:us-east-1:openai.gpt-6.1-sol", (2.2, 11.0))):
        assert rows[mid] == (*want, "offer:offer-wbhj4kycntgkk"), mid


def test_per_source_seed_dates_name_seeded_sources_checked_after_the_default():
    """SEED_SOURCE_DATES holds only the offers checked after the default: the v2.32.0 offers (2026-09-30) and the
    v2.33.0 Haiku 5.5 offer (2026-10-07); every key is a source a seed row cites."""
    assert {sid: d.isoformat() for sid, d in SEED_SOURCE_DATES.items()} == {
        "offer:offer-5fu2rhus3byrs": "2026-09-30", "offer:offer-wbhj4kycntgkk": "2026-09-30",
        "offer:offer-u3aih6zr7uw5u": "2026-10-07"}
    assert set(SEED_SOURCE_DATES) <= {src for *_, src in seed_rows(ACTIVE).values()}
    assert all(d > SEED_SOURCE_DATE for d in SEED_SOURCE_DATES.values())
