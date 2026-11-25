"""OpenAI GPT 6.2 Astra, GPT 6.2 Sol 편입 (v2.44.0, ADR-039).

2026-11-17 실측(호스트 IAM 자격의 단기 Bedrock 토큰, Responses API 스트리밍):
  - 두 모델 모두 Global CRIS(Seoul bedrock-runtime) 200, US CRIS(us-east-1 bedrock-runtime) 200, Mantle us-east-1 200.
    첫 호출부터 200이었다(이전 신모델의 401 "subscription is being set up" 과도 상태 없음).
    Mantle us-east-2와 us-west-2는 호출하지 않았다 — Mantle 인리전은 us-east-1만 쓴다(v2.38.0 사용자 결정).
  - 패리티 reasoning 프로브 형태("17 x 23은?")에서 effort low 각 3회, effort high 각 1회 모두 reasoning_tokens 0
    (Responses와 Chat Completions, Global CRIS).
  - 벤치 요청 형태(약 55.8k 토큰 고정 컨텍스트)로 여섯 채널 모두 200, 둘째 호출 cached_tokens 55839.
  - 오퍼: GPT 6.2 Astra offer-i5wczxyjg7weu(In-Region과 US CRIS $8.80/$44, Global $8/$40), GPT 6.2 Sol
    offer-7vsvjk6xmsl7c($2.20/$11, $2/$10). 긴 컨텍스트 출력이 짧은 컨텍스트 출력보다 높아 정상값이다.
    Astra 오퍼에는 ultrafast 차원이 있고 파서는 `_standard` 차원만 읽는다.
  - OpenAI 문서(2026-11-17): gpt-6.2-astra $8/$40, gpt-6.2-sol $2/$10. 캐시 쓰기 열 이름은 2026-10-27부터 "30m write"다.
"""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import gptbench
import models
import pricing_seed
import pricing_sync
import prober
import visibility
from model_explorer import examples
from parity.catalog import is_reasoning_capable
from price_history import current_rows
from pricing_parsers import UnitPrice, parse_openai_pricing_md, select_offer_price, single_public_offer
from pricing_payload import build_pricing_payload
from pricing_seed import OPENAI_LIST_SEED, SEED, SEED_SOURCE_DATES, seed_extra
from pricing_sources import FAMILY_ORDER, active_channels, price_identity
from pricing_sync import _plausible_long
from routers.cost import _channel
from routers.reliability import _parse_label

FIXTURES = Path(__file__).parent / "fixtures" / "pricing"
NOW = datetime(2026, 11, 17, 23, 0, tzinfo=timezone.utc)

# family → (env, FM id, family_key, offer id, (Global in, out), (US와 in-region in, out))
MODELS = {
    "GPT 6.2 Astra": ("BEDROCK_OPENAI_GPT_62_ASTRA_MODEL_ID", "openai.gpt-6.2-astra", "gpt-6.2-astra",
                      "offer-i5wczxyjg7weu", (8.0, 40.0), (8.8, 44.0)),
    "GPT 6.2 Sol": ("BEDROCK_OPENAI_GPT_62_SOL_MODEL_ID", "openai.gpt-6.2-sol", "gpt-6.2-sol",
                    "offer-7vsvjk6xmsl7c", (2.0, 10.0), (2.2, 11.0)),
}
_BASE_URLS = (
    ("OPENAI_GLOBAL_BASE_URL", "https://gl/openai/v1"),
    ("OPENAI_US_BASE_URL", "https://us/openai/v1"),
    ("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1"),
    ("OPENAI_US_EAST_2_BASE_URL", "https://e2/openai/v1"),
    ("OPENAI_US_WEST_2_BASE_URL", "https://w2/openai/v1"),
)
# 운영 CDK가 주입하던 모델 id env (v2.44.0 — v2.45.0은 GPT 5.6 id 세 개를 더 주입한다, test_reenable_gpt56.py)
_PRODUCTION_ENV = {
    "BEDROCK_OPENAI_GPT_62_ASTRA_MODEL_ID": "openai.gpt-6.2-astra",
    "BEDROCK_OPENAI_GPT_62_SOL_MODEL_ID": "openai.gpt-6.2-sol",
    "BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID": "openai.gpt-6.1-sol",
    "BEDROCK_OPENAI_GPT_61_TERRA_MODEL_ID": "openai.gpt-6.1-terra",
    "BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID": "openai.gpt-6-astra",
    "BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID": "openai.gpt-6-sol",
    "BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID": "openai.gpt-6-luna",
}


def _keys(fm: str) -> list[str]:
    return [f"openai:global:global.{fm}", f"openai:us:us.{fm}", f"openai:us-east-1:{fm}"]


def _labels(family: str, fm: str) -> dict[str, str]:
    return dict(zip(_keys(fm), (f"OpenAI {family} (Global)", f"OpenAI {family} (US)", f"OpenAI {family} (us-east-1)")))


def U(inp, out, **extra):
    return UnitPrice(input=D(str(inp)), output=D(str(out)), **{k: D(str(v)) for k, v in extra.items()})


def _register(monkeypatch, model_env):
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.delenv("OPENAI_1P_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    for env, url in _BASE_URLS:
        monkeypatch.setenv(env, url)
    for env in _PRODUCTION_ENV:
        monkeypatch.delenv(env, raising=False)
    for env, value in model_env.items():
        monkeypatch.setenv(env, value)
    prober._register_openai_models()
    return {k: v for k, v in prober.AVAILABLE_MODELS.items() if k.startswith("openai:")}


# ---------------------------------------------------------------- prober

def test_gpt62_specs_come_first_astra_then_sol():
    assert prober._OPENAI_MODEL_SPECS[:2] == [
        ("BEDROCK_OPENAI_GPT_62_ASTRA_MODEL_ID", "GPT 6.2 Astra", ("global", "us", "us-east-1")),
        ("BEDROCK_OPENAI_GPT_62_SOL_MODEL_ID", "GPT 6.2 Sol", ("global", "us", "us-east-1")),
    ]
    assert prober._OPENAI_1P_MODEL_SPECS == []  # no 1P spec for the new models either


@pytest.mark.parametrize("family", list(MODELS))
def test_each_gpt62_model_registers_exactly_three_channels(monkeypatch, family):
    """Global CRIS + US CRIS + Mantle us-east-1 — us-east-2/us-west-2는 base URL env가 있어도 등록하지 않는다."""
    env, fm, *_ = MODELS[family]
    openai = _register(monkeypatch, {env: fm})
    # 라벨은 DB model_name에 영구 기록 — frontend MODEL_COLORS 키와 바이트 단위로 일치해야 한다.
    assert openai == _labels(family, fm)


@pytest.mark.parametrize("family", list(MODELS))
def test_each_gpt62_model_is_skipped_without_its_model_id_env(monkeypatch, family):
    # env 누락이면 그 모델 3채널이 조용히 빠진다 — CDK가 두 스택 모두에 주입해야 하는 이유.
    env, fm, *_ = MODELS[family]
    openai = _register(monkeypatch, {k: v for k, v in _PRODUCTION_ENV.items() if k != env})
    assert not [k for k in openai if fm in k]
    assert len(openai) == 18


def test_production_env_registers_21_openai_channels(monkeypatch):
    openai = _register(monkeypatch, _PRODUCTION_ENV)
    assert len(openai) == 21  # Mantle us-east-1 7 + Global CRIS 7 + US CRIS 7 (15 in v2.43.0)
    assert sorted(k for k in openai if k.split(":")[1] not in prober._OPENAI_PSEUDO_REGIONS) == sorted(
        f"openai:us-east-1:{fm}" for fm in _PRODUCTION_ENV.values())
    for family, (_, fm, *_rest) in MODELS.items():
        assert {k: openai[k] for k in _keys(fm)} == _labels(family, fm)


def test_gpt62_ids_and_labels_do_not_collide_with_other_family_markers():
    for family, (_, fm, *_rest) in MODELS.items():
        for key, label in _labels(family, fm).items():
            # substring markers of the neighbours: the GPT 6 and GPT 6.1 ids, and the retired GPT 5.x reasoning marker
            for other in ("gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-5"):
                assert other not in key, (key, other)
            for other in ("GPT 6 Astra", "GPT 6 Sol", "GPT 6.1 Sol"):
                assert other not in label, (label, other)
            assert is_reasoning_capable(key) is False  # reasoning_tokens 0 at effort low and high (2026-11-17)
            assert not any(p in label for p in visibility._DEFAULT_HIDDEN.split(",")), label  # no hide pattern matches


def test_reliability_cost_and_explorer_read_the_new_channels():
    assert _parse_label("OpenAI GPT 6.2 Astra (Global)") == ("GPT 6.2 Astra", "OpenAI Global")
    assert _parse_label("OpenAI GPT 6.2 Sol (US)") == ("GPT 6.2 Sol", "OpenAI US")
    assert _parse_label("OpenAI GPT 6.2 Sol (us-east-1)") == ("GPT 6.2 Sol", "OpenAI us-east-1")
    for _, fm, *_rest in MODELS.values():
        g, us, e1 = _keys(fm)
        assert {_channel(k) for k in (g, us, e1)} == {"OpenAI"}
        by_key = {k: examples.code_examples(k) for k in (g, us, e1)}
        assert all([e["api_id"] for e in ex] == ["responses"] for ex in by_key.values())  # one Responses example each
        assert f'model="global.{fm}"' in by_key[g][0]["code"]["en"]
        assert "bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1" in by_key[g][0]["code"]["en"]
        assert f'model="us.{fm}"' in by_key[us][0]["code"]["en"]
        assert "bedrock-runtime.us-east-1.amazonaws.com/openai/v1" in by_key[us][0]["code"]["en"]
        assert f'model="{fm}"' in by_key[e1][0]["code"]["en"]
        assert "bedrock-mantle.us-east-1.api.aws/openai/v1" in by_key[e1][0]["code"]["en"]


# ---------------------------------------------------------------- bench

def test_bench_appends_gpt62_astra_then_sol_in_both_lanes(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    for env, url in _BASE_URLS:
        monkeypatch.setenv(env, url)
    for env, value in _PRODUCTION_ENV.items():
        monkeypatch.setenv(env, value)
    assert gptbench._BENCH_SPECS[-3:-1] == [  # the last entry is GPT 5.6 Terra since v2.45.0, skipped without its env
        ("GPT 6.2 Astra", "BEDROCK_OPENAI_GPT_62_ASTRA_MODEL_ID", ("global", "us", "us-east-1")),
        ("GPT 6.2 Sol", "BEDROCK_OPENAI_GPT_62_SOL_MODEL_ID", ("global", "us", "us-east-1")),
    ]
    chans = gptbench.bench_channels()
    assert [c["model_id"] for c in chans][-6:] == _keys("openai.gpt-6.2-astra") + _keys("openai.gpt-6.2-sol")
    lanes = gptbench.bench_lanes(chans)
    assert {lane: len(items) for lane, items in lanes.items()} == {"cris": 14, "mantle-us-east-1": 7}  # 10 and 5 in v2.43.0
    assert [ch["family"] for _, ch in lanes["mantle-us-east-1"]][-2:] == ["GPT 6.2 Astra", "GPT 6.2 Sol"]
    # every bench channel is a prober channel with the same label
    registered = _register(monkeypatch, _PRODUCTION_ENV)
    assert {c["model_id"]: c["model_name"] for c in chans} == registered


# ---------------------------------------------------------------- unit prices

def test_family_order_puts_gpt62_in_front_of_gpt61():
    at = FAMILY_ORDER.index("GPT 6.2 Astra")
    assert FAMILY_ORDER[at - 1:at + 3] == ("Nova 2.0 Lite", "GPT 6.2 Astra", "GPT 6.2 Sol", "GPT 6.1 Sol")


@pytest.mark.parametrize("family", list(MODELS))
def test_price_identity_and_seed(family):
    _, fm, family_key, offer, global_price, regional_price = MODELS[family]
    g, us, e1 = _keys(fm)
    for key, channel in ((g, "global"), (us, "us"), (e1, "inregion:us-east-1")):
        ident = price_identity(key)
        assert (ident.family_key, ident.family, ident.provider, ident.channel, ident.source_kind, ident.source_ref) == (
            family_key, family, "openai", channel, "offer", fm), key
    assert SEED[g] == (*global_price, f"offer:{offer}")
    assert SEED[us] == SEED[e1] == (*regional_price, f"offer:{offer}")  # US CRIS = In Region (one offer dimension)
    assert SEED_SOURCE_DATES[f"offer:{offer}"].isoformat() == "2026-11-17"
    assert OPENAI_LIST_SEED[family_key] == (*global_price, "openai-pricing")  # OpenAI price = Bedrock Global CRIS
    ident = price_identity(f"openai-list:{family_key}")
    assert (ident.channel, ident.source_kind, ident.source_ref) == ("openai_list", "openai_doc", family_key)


@pytest.mark.parametrize("family, fixture, global_, regional", [
    ("GPT 6.2 Astra", "offers_gpt-6.2-astra.json",
     U(8, 40, cache_read="0.4", cache_write=10, long_input=16, long_output=60, long_cache_read="0.8", long_cache_write=20),
     U("8.8", 44, cache_read="0.44", cache_write=11, long_input="17.6", long_output=66, long_cache_read="0.88",
       long_cache_write=22)),
    ("GPT 6.2 Sol", "offers_gpt-6.2-sol.json",
     U(2, 10, cache_read="0.1", cache_write="2.5", long_input=4, long_output=15, long_cache_read="0.2", long_cache_write=5),
     U("2.2", 11, cache_read="0.11", cache_write="2.75", long_input="4.4", long_output="16.5", long_cache_read="0.22",
       long_cache_write="5.5")),
])
def test_offer_fixtures_give_the_seed_prices(family, fixture, global_, regional):
    _, fm, _, offer, global_price, regional_price = MODELS[family]
    offer_id, card = single_public_offer(json.loads((FIXTURES / fixture).read_text(encoding="utf-8")))
    assert offer_id == offer
    assert select_offer_price(card, "global") == global_
    assert select_offer_price(card, "us") == select_offer_price(card, "inregion:us-east-1") == regional
    assert (float(global_.input), float(global_.output)) == global_price
    assert (float(regional.input), float(regional.output)) == regional_price
    g, us, e1 = _keys(fm)
    for key, price in ((g, global_), (us, regional), (e1, regional)):  # the seed extras are the offer's extras
        extras = seed_extra(key, price_identity(key))
        assert {f: v for f, v in extras.items() if v is not None} == {
            f: float(getattr(price, f)) for f in extras if getattr(price, f) is not None}, key


def test_the_astra_offer_has_ultrafast_dimensions_the_parser_never_reads():
    """The GPT 6.2 Astra rate card adds `_ultrafast` dimensions (3x Standard). Only `_standard` is an allow-listed
    suffix, so they change nothing — like `_priority` and `_flex`."""
    _, card = single_public_offer(json.loads((FIXTURES / "offers_gpt-6.2-astra.json").read_text(encoding="utf-8")))
    ultrafast = [e for e in card if e["dimension"].endswith("_ultrafast")]
    assert len(ultrafast) == 16 and {"input_tokens_global_ultrafast", "output_tokens_ultrafast"} <= {
        e["dimension"] for e in ultrafast}
    without = [e for e in card if not e["dimension"].endswith(("_ultrafast", "_priority", "_flex"))]
    for channel in ("global", "us", "inregion:us-east-1"):
        assert select_offer_price(card, channel) == select_offer_price(without, channel)


@pytest.mark.parametrize("family", list(MODELS))
def test_seed_keeps_the_plausible_long_context(caplog, family):
    """Both offers' long-context output is above the short one (unlike the 6.1 Sol offer) — nothing is dropped."""
    _, fm, *_ = MODELS[family]
    for key in _keys(fm):
        extras = seed_extra(key, price_identity(key))
        inp, out, _ = SEED[key]
        assert extras["long_input"] == pytest.approx(inp * 2) and extras["long_output"] == pytest.approx(out * 1.5), key
        price = UnitPrice(input=inp, output=out, **{f: extras[f] for f in (
            "long_input", "long_output", "long_cache_read", "long_cache_write")})
        with caplog.at_level(logging.WARNING, logger="pricing_sync"):
            assert _plausible_long(price, fm) == price
    assert caplog.messages == []


def test_openai_doc_of_20261117_lists_both_models():
    """The 2026-11-17 OpenAI pricing doc: both Standard rows give the seeded input, output, cache read and long context.
    The cache-write columns are named "30m write" / "12h write" since 2026-10-27, so the parser leaves both cache-write
    fields None there (the stored seed value is kept — a None observation is not a change)."""
    prices = parse_openai_pricing_md((FIXTURES / "openai_pricing_20261117.md").read_text(encoding="utf-8"))
    for family_key, want in (("gpt-6.2-astra", (8.0, 40.0, 0.4, 16.0, 60.0, 0.8)), ("gpt-6.2-sol", (2.0, 10.0, 0.1, 4.0, 15.0, 0.2))):
        p = prices[family_key]
        assert tuple(float(v) for v in (p.input, p.output, p.cache_read, p.long_input, p.long_output, p.long_cache_read)) == want
        assert (p.cache_write, p.long_cache_write) == (None, None)
    assert {"gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna"} <= set(prices)  # the others stay listed


def test_openai_list_seed_extras_are_the_30m_write_column():
    """The older-layout fixture (cache writes = the doc's 30m write) carries the two rows with the seeded cache writes."""
    prices = parse_openai_pricing_md((FIXTURES / "openai_pricing.md").read_text(encoding="utf-8"))
    for family_key, (cache_write, long_cache_write) in (("gpt-6.2-astra", (10.0, 20.0)), ("gpt-6.2-sol", (2.5, 5.0))):
        p = prices[family_key]
        assert (float(p.cache_write), float(p.long_cache_write)) == (cache_write, long_cache_write)
        extras = seed_extra(f"openai-list:{family_key}", price_identity(f"openai-list:{family_key}"))
        assert (extras["cache_write"], extras["long_cache_write"]) == (cache_write, long_cache_write)
        assert {f: v for f, v in extras.items() if v is not None} == {
            f: float(getattr(p, f)) for f in extras if getattr(p, f) is not None}


# ---------------------------------------------------------------- one sync against the 2026-11-17 sources

def _fail(*_):
    raise AssertionError("no such source in this test")


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def test_sync_verifies_the_gpt62_seeds_without_review(engine):
    labels = {k: v for family, (_, fm, *_rest) in MODELS.items() for k, v in _labels(family, fm).items()}
    active = active_channels(labels, [])
    assert sorted(m for m in active if m.startswith("openai-list:")) == ["openai-list:gpt-6.2-astra", "openai-list:gpt-6.2-sol"]
    assert pricing_seed.ensure_seed(engine, active) == 8  # six channels + two OpenAI official prices
    Session = sessionmaker(bind=engine, autoflush=False)
    fixture_of = {fm: f"offers_{fk}.json" for _, fm, fk, *_rest in MODELS.values()}
    fetchers = pricing_sync.Fetchers(
        offers=lambda fm: json.loads((FIXTURES / fixture_of[fm]).read_text(encoding="utf-8")),
        pricelist=_fail, anthropic_doc=_fail,
        openai_doc=lambda: (FIXTURES / "openai_pricing_20261117.md").read_text(encoding="utf-8"))
    pricing_sync.run_sync(Session, active, fetchers, now=lambda: NOW)

    with Session() as db:
        assert db.query(models.PriceHistory).count() == 8  # no new row: every observation equals its seed
        assert db.query(models.PriceHistory).filter(models.PriceHistory.status == "pending_review").count() == 0
        current = current_rows(db, active, now=NOW)
        for mid, row in current.items():
            want = pricing_seed.seed_rows(active)[mid]
            assert (row.input_per_mtok, row.output_per_mtok) == want[:2], mid
            assert row.observed_at is not None, mid  # the sync observed the seed value, so the seed row is confirmed
        astra_list = current["openai-list:gpt-6.2-astra"]
        # the doc's renamed column gives no cache write; the seeded 30m write stays
        assert (astra_list.cache_read_per_mtok, astra_list.cache_write_per_mtok) == (0.4, 10.0)
        payload = build_pricing_payload(db, active, now=NOW)
    assert [f["family_key"] for f in payload["families"]] == ["gpt-6.2-astra", "gpt-6.2-sol"]
    astra, sol = payload["families"]
    assert (astra["family"], sol["family"]) == ("GPT 6.2 Astra", "GPT 6.2 Sol")
    assert (astra["tiers"]["global"]["input"], astra["tiers"]["us"]["output"], astra["tiers"]["openai_list"]["input"]) == (8, 44, 8)
    assert [c["regions"] for c in astra["tiers"]["in_region"]] == [["us-east-1"]]
    assert sol["tiers"]["in_region"][0]["long"] == {"input": 4.4, "output": 16.5, "cache_read": 0.22, "cache_write": 5.5}
