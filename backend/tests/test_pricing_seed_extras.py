"""단가 seed의 캐시, 긴 컨텍스트 단가 (v2.31.0) — 채널별 seed_extra 값, 새 seed 행, v2.30.0 seed 행의 NULL 채우기."""

import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from pricing_parsers import EXTRA_FIELDS
from pricing_seed import ensure_seed, seed_extra, seed_rows
from pricing_sources import EPOCH, OPENAI_SOURCE_ID, active_channels
from tests.pricing_catalog import ACTIVE_MODELS

ACTIVE = active_channels(ACTIVE_MODELS, ["(1P)"])  # 활성 55채널 + OpenAI 공식 가격 8채널(openai-list:<family_key>)
COLUMNS = [f"{f}_per_mtok" for f in EXTRA_FIELDS]
CACHE = ("cache_read", "cache_write", "cache_write_1h")
GPT = ("cache_read", "cache_write", "long_input", "long_output", "long_cache_read", "long_cache_write")
N = None

# Interface Contract C8 — pricing_seed의 표와 따로 적는다(표를 옮겨 적다 틀리면 여기서 잡힌다).
CLAUDE_GLOBAL = {  # 캐시 읽기, 5분 쓰기, 1시간 쓰기 — Bedrock Global = Claude Platform on AWS(Anthropic 문서)
    "claude-fable-5-1": (0.25, 12.5, 20), "claude-fable-5": (1, 12.5, 20), "claude-opus-5-5": (0.2, 5, 8),
    "claude-opus-5": (0.5, 6.25, 10), "claude-opus-4-8": (0.5, 6.25, 10), "claude-opus-4-7": (0.5, 6.25, 10),
    "claude-opus-4-6": (0.5, 6.25, 10), "claude-sonnet-5": (0.2, 2.5, 4), "claude-sonnet-4-6": (0.3, 3.75, 6),
    "claude-haiku-4-5": (0.1, 1.25, 2),
}
CLAUDE_US = {
    "claude-fable-5-1": (0.275, 13.75, 22), "claude-fable-5": (1.1, 13.75, 22), "claude-opus-5-5": (0.22, 5.5, 8.8),
    "claude-opus-5": (0.55, 6.875, 11), "claude-opus-4-8": (0.55, 6.875, 11), "claude-opus-4-7": (0.55, 6.875, 11),
    "claude-opus-4-6": (0.55, 6.875, 11), "claude-sonnet-5": (0.22, 2.75, 4.4),
    "claude-sonnet-4-6": (0.33, 4.125, 6.6), "claude-haiku-4-5": (0.11, 1.375, 2.2),
}
GPT_STANDARD = {  # US CRIS와 모든 in-region 채널 — GPT 순서
    "gpt-6-astra": (1.1, 13.75, 22, 82.5, 2.2, 27.5), "gpt-6-sol": (0.22, 2.75, 4.4, 16.5, 0.44, 5.5),
    "gpt-6-luna": (0.011, 0.1375, 0.22, 0.825, 0.022, 0.275), "gpt-5.6-sol": (0.44, 5.5, 8.8, 33, 0.88, 11),
    "gpt-5.6-terra": (0.22, 2.75, 4.4, 19.8, 0.44, 5.5), "gpt-5.6-luna": (0.022, 0.275, 0.44, 1.98, 0.044, 0.55),
    "gpt-5.5": (0.55, N, 11, 49.5, 1.1, N), "gpt-5.4": (0.275, N, 5.5, 24.75, 0.55, N),
}
GPT_GLOBAL = {  # Global CRIS (GPT 5.5, 5.4는 Global 채널 없음)
    "gpt-6-astra": (1, 12.5, 20, 75, 2, 25), "gpt-6-sol": (0.2, 2.5, 4, 15, 0.4, 5),
    "gpt-6-luna": (0.01, 0.125, 0.2, 0.75, 0.02, 0.25), "gpt-5.6-sol": (0.4, 5, 8, 30, 0.8, 10),
    "gpt-5.6-terra": (0.2, 2.5, 4, 18, 0.4, 5), "gpt-5.6-luna": (0.02, 0.25, 0.4, 1.8, 0.04, 0.5),
}
OPENAI_LIST = {  # 입력, 출력, 그다음 GPT 순서 — OpenAI 문서 Standard 표
    "gpt-6-astra": (10, 50, 1, 12.5, 20, 75, 2, 25), "gpt-6-sol": (2, 10, 0.2, 2.5, 4, 15, 0.4, 5),
    "gpt-6-luna": (0.1, 0.5, 0.01, 0.125, 0.2, 0.75, 0.02, 0.25), "gpt-5.6-sol": (4, 20, 0.4, 5, 8, 30, 0.8, 10),
    "gpt-5.6-terra": (2, 12, 0.2, 2.5, 4, 18, 0.4, 5), "gpt-5.6-luna": (0.2, 1.2, 0.02, 0.25, 0.4, 1.8, 0.04, 0.5),
    "gpt-5.5": (5, 30, 0.5, N, 10, 45, 1, N), "gpt-5.4": (2.5, 15, 0.25, N, 5, 22.5, 0.5, N),
}
NOVA = {"cache_read": 0.0825, "cache_write": 0}  # Nova 캐시 쓰기는 공식 $0 — None이 아니라 0

OPUS_G, OPUS_US = "global.anthropic.claude-opus-5-5", "us.anthropic.claude-opus-5-5"
OPUS46_US, SOL_G = "us.anthropic.claude-opus-4-6-v1", "openai:global:global.openai.gpt-5.6-sol"
GPT54_E1, NOVA_ID, CP_HAIKU = "openai:us-east-1:openai.gpt-5.4", "us.amazon.nova-2-lite-v1:0", "anthropic:claude-haiku-4-5-20251001"


def _expected(ident) -> dict:
    if ident.provider == "amazon":
        named = NOVA
    elif ident.provider == "anthropic":
        named = dict(zip(CACHE, (CLAUDE_US if ident.channel == "us" else CLAUDE_GLOBAL)[ident.family_key]))
    elif ident.channel == "openai_list":
        named = dict(zip(GPT, OPENAI_LIST[ident.family_key][2:]))
    else:
        named = dict(zip(GPT, (GPT_GLOBAL if ident.channel == "global" else GPT_STANDARD)[ident.family_key]))
    return {**dict.fromkeys(EXTRA_FIELDS), **named}


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _rows(eng):
    with sessionmaker(bind=eng)() as s:
        return {r.model_id: r for r in s.execute(select(models.PriceHistory)).scalars()}


def _extras_of(row) -> dict:
    return {f: getattr(row, c) for f, c in zip(EXTRA_FIELDS, COLUMNS)}


def _add(eng, model_id, inp, out, status="seed", **extras):
    ident = ACTIVE[model_id]
    with sessionmaker(bind=eng)() as s:
        s.add(models.PriceHistory(model_id=model_id, family_key=ident.family_key, channel=ident.channel,
                                  input_per_mtok=inp, output_per_mtok=out, effective_from=EPOCH,
                                  source_id="offer:v2300-seed", status=status, **extras))
        s.commit()


def test_the_active_set_has_55_channels_plus_eight_openai_list_channels():
    assert len(ACTIVE) == 63
    assert sorted(i.family_key for i in ACTIVE.values() if i.channel == "openai_list") == sorted(OPENAI_LIST)


@pytest.mark.parametrize("model_id", sorted(ACTIVE))
def test_every_active_channel_has_exactly_the_contract_extras(model_id):
    got = seed_extra(model_id, ACTIVE[model_id])
    assert got == _expected(ACTIVE[model_id]), model_id
    assert list(got) == list(EXTRA_FIELDS)
    assert all(v is None or type(v) is float for v in got.values()), got


def test_openai_list_seed_rows_are_the_openai_doc_input_and_output():
    rows = seed_rows(ACTIVE)
    for family_key, values in OPENAI_LIST.items():
        assert rows[f"openai-list:{family_key}"] == (values[0], values[1], OPENAI_SOURCE_ID), family_key


def test_seed_extra_returns_a_copy():
    first = seed_extra(OPUS_G, ACTIVE[OPUS_G])
    first["cache_read"] = 99.0
    assert seed_extra(OPUS_G, ACTIVE[OPUS_G])["cache_read"] == 0.2


def test_new_seed_rows_carry_the_extras_and_a_rerun_changes_nothing(engine, caplog):
    with caplog.at_level(logging.INFO, logger="pricing_seed"):
        assert ensure_seed(engine, ACTIVE) == 63
    rows = _rows(engine)
    assert set(rows) == set(ACTIVE)
    for model_id, row in rows.items():
        assert _extras_of(row) == _expected(ACTIVE[model_id]), model_id
        assert (row.status, row.observed_at) == ("seed", None)
    assert rows[NOVA_ID].cache_write_per_mtok == 0.0 and rows[GPT54_E1].cache_write_per_mtok is None
    assert "filled cache/long-context" not in caplog.text
    assert ensure_seed(engine, ACTIVE) == 0
    assert {m: _extras_of(r) for m, r in _rows(engine).items()} == {m: _extras_of(r) for m, r in rows.items()}


def test_v230_seed_rows_get_only_their_null_extras_filled(engine, caplog):
    _add(engine, OPUS_G, 4.0, 20.0)                              # v2.30.0 seed row: every extra NULL
    _add(engine, GPT54_E1, 2.75, 16.5)
    _add(engine, NOVA_ID, 0.33, 2.75)
    _add(engine, CP_HAIKU, 1.0000000004, 5.0)                    # equal to the seed at 6 decimals
    _add(engine, OPUS_US, 4.4, 22.0, cache_read_per_mtok=0.3)    # a value that is already set is never overwritten
    _add(engine, OPUS46_US, 5.0, 25.0)                           # not the seed value (5.5 / 27.5): left alone
    _add(engine, SOL_G, 4.0, 20.0, status="verified")            # only status='seed' rows are filled
    with caplog.at_level(logging.INFO, logger="pricing_seed"):
        assert ensure_seed(engine, ACTIVE) == 63 - 7              # the return value still counts inserted rows only
    assert "Price seed filled cache/long-context fields on 5 rows" in caplog.messages
    rows = _rows(engine)
    for model_id in (OPUS_G, GPT54_E1, NOVA_ID, CP_HAIKU):
        assert _extras_of(rows[model_id]) == _expected(ACTIVE[model_id]), model_id
    assert rows[GPT54_E1].cache_write_per_mtok is None and rows[GPT54_E1].long_cache_write_per_mtok is None
    assert rows[NOVA_ID].cache_write_per_mtok == 0.0
    assert (rows[OPUS_US].cache_read_per_mtok, rows[OPUS_US].cache_write_per_mtok,
            rows[OPUS_US].cache_write_1h_per_mtok) == (0.3, 5.5, 8.8)
    assert _extras_of(rows[OPUS46_US]) == dict.fromkeys(EXTRA_FIELDS)
    assert _extras_of(rows[SOL_G]) == dict.fromkeys(EXTRA_FIELDS)
    assert (rows[OPUS_G].input_per_mtok, rows[OPUS_G].output_per_mtok, rows[OPUS_G].status) == (4.0, 20.0, "seed")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="pricing_seed"):
        assert ensure_seed(engine, ACTIVE) == 0                   # idempotent: nothing left to insert or fill
    assert "filled cache/long-context" not in caplog.text
    assert _extras_of(_rows(engine)[OPUS_US])["cache_read"] == 0.3


class _Begin:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


def test_postgres_fills_inside_the_seed_transaction_after_the_lock():
    log: list[str] = []
    old = SimpleNamespace(id=7, model_id=NOVA_ID, input_per_mtok=0.33, output_per_mtok=2.75,
                          **{c: None for c in COLUMNS})

    def execute(stmt, params=None):
        sql = str(stmt)
        log.append(sql)
        if sql.startswith("SELECT DISTINCT"):
            return SimpleNamespace(scalars=lambda: iter([NOVA_ID]))
        if sql.startswith("SELECT price_history.id"):
            return SimpleNamespace(all=lambda: [old])
        return SimpleNamespace()

    pg = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"),
                         begin=lambda: _Begin(SimpleNamespace(execute=execute)))
    assert ensure_seed(pg, {NOVA_ID: ACTIVE[NOVA_ID], OPUS_G: ACTIVE[OPUS_G]}) == 1
    assert log[:3] == ["SET LOCAL statement_timeout = '30000'", "SET LOCAL lock_timeout = '5000'",
                       "SELECT pg_advisory_xact_lock(917350003)"]
    assert [s.split()[0] + " " + s.split()[1] for s in log[3:]] == [
        "SELECT DISTINCT", "INSERT INTO", "SELECT price_history.id,", "UPDATE price_history"]
    assert "cache_read_per_mtok" in log[-1] and "cache_write_per_mtok" in log[-1] and "long_input" not in log[-1]
