"""OpenAI GPT 5.6 Sol, Terra, Luna 복귀 (v2.45.0, ADR-040) — 사용자 요청 2026-11-25 "gpt 5.6을 다시 활성화해주세요".

v2.43.0(ADR-038)에 뺐던 여섯 채널을 그때와 같은 구성으로 되살린다: 모델마다 Global CRIS와 Mantle us-east-1.
GPT 5.6 Terra는 벤치에도 돌아온다(Global, us-east-1 — 목록 끝). GPT 5.5, Claude Opus 4.8, 휴면 1P 스펙은 빠진 그대로다
(test_retire_opus48_gpt55.py).

2026-11-25 실측(호스트 IAM 자격의 단기 Bedrock 토큰, Responses API 스트리밍):
  - FM openai.gpt-5.6-{sol,terra,luna}는 서울과 us-east-1에서 ACTIVE(INFERENCE_PROFILE 전용), global. 프로파일 ACTIVE.
    us-east-1에는 us. 프로파일도 있지만 v2.42.x에 재지 않던 채널이라 넣지 않았다.
  - 여섯 채널 모두 첫 호출부터 200. 벤치 요청 형태로 GPT 5.6 Terra 두 채널 200, 둘째 호출 cached_tokens 55837.
  - 오퍼는 v2.42.x seed와 같다: Sol offer-gnqokrqqvdbgw(In-Region $4.40/$22, Global $4/$20 — 프로모션 단가),
    Terra offer-3dvyrx3okd4lq($2.20/$13.20, $2/$12), Luna offer-bklbyf2ewuawu($0.22/$1.32, $0.20/$1.20).
  - OpenAI 문서: gpt-5.6-sol $4/$20, terra $2/$12, luna $0.20/$1.20. 프로모션 문장은 2026-11-17 문서부터
    "GPT-5.6 Sol's promotional pricing is available until November 30, 2026"이고 2026-11-25에도 같다.
"""

import json
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
import pricing_sources
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
from routers.cost import _channel
from routers.reliability import _parse_label
from tests.pricing_catalog import ACTIVE_MODELS, REENABLED_V245_MODELS

FIXTURES = Path(__file__).parent / "fixtures" / "pricing"
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)

# family → (env, FM id, family_key, offer id, (Global in, out), (in-region in, out))
MODELS = {
    "GPT 5.6 Sol": ("BEDROCK_OPENAI_GPT_56_SOL_MODEL_ID", "openai.gpt-5.6-sol", "gpt-5.6-sol",
                    "offer-gnqokrqqvdbgw", (4.0, 20.0), (4.4, 22.0)),
    "GPT 5.6 Terra": ("BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID", "openai.gpt-5.6-terra", "gpt-5.6-terra",
                      "offer-3dvyrx3okd4lq", (2.0, 12.0), (2.2, 13.2)),
    "GPT 5.6 Luna": ("BEDROCK_OPENAI_GPT_56_LUNA_MODEL_ID", "openai.gpt-5.6-luna", "gpt-5.6-luna",
                     "offer-bklbyf2ewuawu", (0.2, 1.2), (0.22, 1.32)),
}
_BASE_URLS = (
    ("OPENAI_GLOBAL_BASE_URL", "https://gl/openai/v1"),
    ("OPENAI_US_BASE_URL", "https://us/openai/v1"),
    ("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1"),
    ("OPENAI_US_EAST_2_BASE_URL", "https://e2/openai/v1"),
    ("OPENAI_US_WEST_2_BASE_URL", "https://w2/openai/v1"),
)
# 운영 CDK가 주입하는 모델 id env (v2.45.0)
_PRODUCTION_ENV = {
    "BEDROCK_OPENAI_GPT_62_ASTRA_MODEL_ID": "openai.gpt-6.2-astra",
    "BEDROCK_OPENAI_GPT_62_SOL_MODEL_ID": "openai.gpt-6.2-sol",
    "BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID": "openai.gpt-6.1-sol",
    "BEDROCK_OPENAI_GPT_61_TERRA_MODEL_ID": "openai.gpt-6.1-terra",
    "BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID": "openai.gpt-6-astra",
    "BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID": "openai.gpt-6-sol",
    "BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID": "openai.gpt-6-luna",
    "BEDROCK_OPENAI_GPT_56_SOL_MODEL_ID": "openai.gpt-5.6-sol",
    "BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID": "openai.gpt-5.6-terra",
    "BEDROCK_OPENAI_GPT_56_LUNA_MODEL_ID": "openai.gpt-5.6-luna",
}


def _keys(fm: str) -> list[str]:
    return [f"openai:global:global.{fm}", f"openai:us-east-1:{fm}"]


def _labels(family: str, fm: str) -> dict[str, str]:
    return dict(zip(_keys(fm), (f"OpenAI {family} (Global)", f"OpenAI {family} (us-east-1)")))


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

def test_gpt56_specs_are_back_at_the_end_with_the_v242_regions():
    assert prober._OPENAI_MODEL_SPECS[-3:] == [
        ("BEDROCK_OPENAI_GPT_56_SOL_MODEL_ID", "GPT 5.6 Sol", ("global", "us-east-1")),
        ("BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID", "GPT 5.6 Terra", ("global", "us-east-1")),
        ("BEDROCK_OPENAI_GPT_56_LUNA_MODEL_ID", "GPT 5.6 Luna", ("global", "us-east-1")),
    ]
    assert [family for _, family, _ in prober._OPENAI_MODEL_SPECS if family.startswith("GPT 5.")] == list(MODELS)
    assert prober._OPENAI_1P_MODEL_SPECS == []  # the dormant 1P specs did not come back


@pytest.mark.parametrize("family", list(MODELS))
def test_each_gpt56_model_registers_exactly_two_channels(monkeypatch, family):
    """Global CRIS + Mantle us-east-1 — US CRIS와 us-east-2/us-west-2는 base URL env가 있어도 등록하지 않는다."""
    env, fm, *_ = MODELS[family]
    openai = _register(monkeypatch, {env: fm})
    # 라벨은 DB model_name에 영구 기록 — v2.42.x까지 쌓인 행과 frontend MODEL_COLORS 키와 바이트 단위로 같아야 한다.
    assert openai == _labels(family, fm) == {k: v for k, v in REENABLED_V245_MODELS.items() if fm in k}


@pytest.mark.parametrize("family", list(MODELS))
def test_each_gpt56_model_is_skipped_without_its_model_id_env(monkeypatch, family):
    # env 누락이면 그 모델 2채널이 조용히 빠진다 — CDK가 두 스택 모두에 주입해야 하는 이유.
    env, fm, *_ = MODELS[family]
    openai = _register(monkeypatch, {k: v for k, v in _PRODUCTION_ENV.items() if k != env})
    assert not [k for k in openai if fm in k]
    assert len(openai) == 25


def test_production_env_registers_27_openai_channels(monkeypatch):
    openai = _register(monkeypatch, _PRODUCTION_ENV)
    assert len(openai) == 27  # Mantle us-east-1 10 + Global CRIS 10 + US CRIS 7 (21 in v2.44.0)
    by_region = {r: sum(1 for k in openai if k.split(":")[1] == r) for r in ("global", "us", "us-east-1")}
    assert by_region == {"global": 10, "us": 7, "us-east-1": 10}
    assert openai == {k: v for k, v in ACTIVE_MODELS.items() if k.startswith("openai:")}
    assert len(ACTIVE_MODELS) == 51  # Bedrock 17 + Claude Platform on AWS 7 + OpenAI 27


def test_gpt56_ids_keep_the_gpt5_reasoning_marker_and_no_hide_pattern():
    assert "GPT 5.6" not in visibility.hidden_patterns()
    for key, label in REENABLED_V245_MODELS.items():
        # the neighbours' substring markers must not match a GPT 5.6 id or label
        for other in ("gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-6.2-astra",
                      "gpt-6.2-sol", "gpt-5.5"):
            assert other not in key, (key, other)
        for other in ("GPT 6 Sol", "GPT 6 Luna", "GPT 6.1 Sol", "GPT 6.1 Terra", "GPT 6.2 Sol", "GPT 5.5"):
            assert other not in label, (label, other)
        assert is_reasoning_capable(key) is True  # parity marker "gpt-5" stayed in v2.43.0 — the cells run as before
        assert not any(p in label for p in visibility.hidden_patterns()), label


def test_stored_gpt56_rows_are_visible_again_and_1p_rows_stay_hidden():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    # labels stored up to v2.42.x: the six channels, and the Mantle regions collection stopped at in v2.38.0
    visible = [*REENABLED_V245_MODELS.values(), "OpenAI GPT 5.6 Sol (us-east-2)", "OpenAI GPT 5.6 Terra (us-west-2)"]
    hidden = ["OpenAI GPT 5.6 Sol (1P)", "OpenAI GPT 5.5 (us-east-1)", "Bedrock Claude Opus 4.8 (Global)"]
    with sessionmaker(bind=engine)() as db:
        run = models.ProbeRun(prompt="p")
        db.add(run)
        db.flush()
        for name in [*visible, *hidden]:
            db.add(models.ProbeResult(run_id=run.id, model_id="x", model_name=name, prompt="p", status="success"))
        db.commit()
        q = visibility.visible_only(db.query(models.ProbeResult.model_name), models.ProbeResult.model_name)
        assert sorted(n for (n,) in q.all()) == sorted(visible)
    engine.dispose()


def test_reliability_cost_and_explorer_read_the_channels():
    assert _parse_label("OpenAI GPT 5.6 Sol (Global)") == ("GPT 5.6 Sol", "OpenAI Global")
    assert _parse_label("OpenAI GPT 5.6 Luna (us-east-1)") == ("GPT 5.6 Luna", "OpenAI us-east-1")
    for _, fm, *_rest in MODELS.values():
        g, e1 = _keys(fm)
        assert {_channel(k) for k in (g, e1)} == {"OpenAI"}
        by_key = {k: examples.code_examples(k) for k in (g, e1)}
        assert all([e["api_id"] for e in ex] == ["responses"] for ex in by_key.values())  # one Responses example each
        assert f'model="global.{fm}"' in by_key[g][0]["code"]["en"]
        assert "bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1" in by_key[g][0]["code"]["en"]
        assert f'model="{fm}"' in by_key[e1][0]["code"]["en"]
        assert "bedrock-mantle.us-east-1.api.aws/openai/v1" in by_key[e1][0]["code"]["en"]


# ---------------------------------------------------------------- bench

def test_bench_appends_gpt56_terra_to_both_lanes_and_leaves_sol_and_luna_out(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    for env, url in _BASE_URLS:
        monkeypatch.setenv(env, url)
    for env, value in _PRODUCTION_ENV.items():
        monkeypatch.setenv(env, value)
    # the end of the list, not its old front seat: a deadline cut then falls on the returning channels first
    assert gptbench._BENCH_SPECS[-1] == ("GPT 5.6 Terra", "BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID", ("global", "us-east-1"))
    assert [family for family, _, _ in gptbench._BENCH_SPECS if family.startswith("GPT 5.")] == ["GPT 5.6 Terra"]
    chans = gptbench.bench_channels()
    assert len(chans) == 23  # 21 in v2.44.0
    assert [c["model_id"] for c in chans][-2:] == _keys("openai.gpt-5.6-terra")
    lanes = gptbench.bench_lanes(chans)
    assert {lane: len(items) for lane, items in lanes.items()} == {"cris": 15, "mantle-us-east-1": 8}  # 14 and 7 in v2.44.0
    assert [ch["family"] for _, ch in lanes["cris"]][-1] == "GPT 5.6 Terra"
    assert [ch["family"] for _, ch in lanes["mantle-us-east-1"]][-1] == "GPT 5.6 Terra"
    # every bench channel is a prober channel with the same label
    registered = _register(monkeypatch, _PRODUCTION_ENV)
    assert {c["model_id"]: c["model_name"] for c in chans}.items() <= registered.items()


# ---------------------------------------------------------------- unit prices

def test_family_order_ends_with_the_gpt56_families():
    assert FAMILY_ORDER[-4:] == ("GPT 6 Luna", "GPT 5.6 Sol", "GPT 5.6 Terra", "GPT 5.6 Luna")
    assert len(FAMILY_ORDER) == 18  # 15 in v2.44.0


@pytest.mark.parametrize("family", list(MODELS))
def test_price_identity_and_seed(family):
    _, fm, family_key, offer, global_price, regional_price = MODELS[family]
    g, e1 = _keys(fm)
    for key, channel in ((g, "global"), (e1, "inregion:us-east-1")):
        ident = price_identity(key)
        assert (ident.family_key, ident.family, ident.provider, ident.channel, ident.source_kind, ident.source_ref) == (
            family_key, family, "openai", channel, "offer", fm), key
    assert price_identity(f"openai:us:us.{fm}") is not None  # classifiable, but no such channel is registered or seeded
    assert f"openai:us:us.{fm}" not in SEED
    assert SEED[g] == (*global_price, f"offer:{offer}")
    assert SEED[e1] == (*regional_price, f"offer:{offer}")
    assert SEED_SOURCE_DATES[f"offer:{offer}"].isoformat() == "2026-11-25"  # the day the offers were read again
    assert OPENAI_LIST_SEED[family_key] == (*global_price, "openai-pricing")  # OpenAI price = Bedrock Global CRIS
    ident = price_identity(f"openai-list:{family_key}")
    assert (ident.channel, ident.source_kind, ident.source_ref) == ("openai_list", "openai_doc", family_key)


@pytest.mark.parametrize("family, fixture, global_, regional", [
    ("GPT 5.6 Sol", "offers_gpt-5.6-sol.json",  # read 2026-11-25
     U(4, 20, cache_read="0.4", cache_write=5, long_input=8, long_output=30, long_cache_read="0.8", long_cache_write=10),
     U("4.4", 22, cache_read="0.44", cache_write="5.5", long_input="8.8", long_output=33, long_cache_read="0.88",
       long_cache_write=11)),
    ("GPT 5.6 Terra", "offers_gpt-5.6-terra.json",  # read 2026-09-27, the same values on 2026-11-25
     U(2, 12, cache_read="0.2", cache_write="2.5", long_input=4, long_output=18, long_cache_read="0.4", long_cache_write=5),
     U("2.2", "13.2", cache_read="0.22", cache_write="2.75", long_input="4.4", long_output="19.8", long_cache_read="0.44",
       long_cache_write="5.5")),
    ("GPT 5.6 Luna", "offers_gpt-5.6-luna.json",
     U("0.2", "1.2", cache_read="0.02", cache_write="0.25", long_input="0.4", long_output="1.8", long_cache_read="0.04",
       long_cache_write="0.5"),
     U("0.22", "1.32", cache_read="0.022", cache_write="0.275", long_input="0.44", long_output="1.98",
       long_cache_read="0.044", long_cache_write="0.55")),
])
def test_offer_fixtures_give_the_seed_prices(family, fixture, global_, regional):
    _, fm, _, offer, global_price, regional_price = MODELS[family]
    offer_id, card = single_public_offer(json.loads((FIXTURES / fixture).read_text(encoding="utf-8")))
    assert offer_id == offer
    assert select_offer_price(card, "global") == global_
    assert select_offer_price(card, "inregion:us-east-1") == regional
    assert (float(global_.input), float(global_.output)) == global_price
    assert (float(regional.input), float(regional.output)) == regional_price
    g, e1 = _keys(fm)
    for key, price in ((g, global_), (e1, regional)):  # the seed extras are the offer's extras
        extras = seed_extra(key, price_identity(key))
        assert {f: v for f, v in extras.items() if v is not None} == {
            f: float(getattr(price, f)) for f in extras if getattr(price, f) is not None}, key


def test_openai_doc_lists_the_three_models_and_the_promo_sentence():
    """The 2026-11-17 OpenAI pricing doc (the same rows and sentence on 2026-11-25): the Standard rows give the seeded
    input, output, cache read and long context. The cache-write columns are "30m write" / "12h write" since 2026-10-27,
    so the parser leaves both cache-write fields None there (a None observation is not a change)."""
    text = (FIXTURES / "openai_pricing_20261117.md").read_text(encoding="utf-8")
    prices = parse_openai_pricing_md(text)
    for family_key, want in (("gpt-5.6-sol", (4.0, 20.0, 0.4, 8.0, 30.0, 0.8)), ("gpt-5.6-terra", (2.0, 12.0, 0.2, 4.0, 18.0, 0.4)),
                             ("gpt-5.6-luna", (0.2, 1.2, 0.02, 0.4, 1.8, 0.04))):
        p = prices[family_key]
        assert tuple(float(v) for v in (p.input, p.output, p.cache_read, p.long_input, p.long_output, p.long_cache_read)) == want
        assert (p.cache_write, p.long_cache_write) == (None, None)
        extras = seed_extra(f"openai-list:{family_key}", price_identity(f"openai-list:{family_key}"))
        assert (extras["cache_read"], extras["long_input"], extras["long_output"], extras["long_cache_read"]) == want[2:]
    assert "GPT-5.6 Sol’s promotional pricing is available until November 30, 2026." in text


def test_the_gpt56_sol_promo_note_is_back_with_the_date_the_doc_states():
    assert [n["kind"] for n in pricing_sources.PRICE_NOTES] == ["promo", "doc_conflict"]
    note = pricing_sources.PRICE_NOTES[0]
    assert (note["family_key"], note["min_until"], note["source"], note["source_id"]) == (
        "gpt-5.6-sol", "2026-11-30", "openai_doc", "openai-pricing")
    # the pre-promotion prices: seeing them means the promotion ended, and the payload drops the note
    assert note["prior_price"] == {"openai_list": {"input": 5, "output": 30}, "global": {"input": 5, "output": 30},
                                   "in_region": {"input": 5.5, "output": 33}}
    for text in (note["text_ko"], note["text_en"]):
        assert "2026-11-25" in text and "2026-11-30" in text
    # the end of the promotion is +25 % input and +50 % output on every tier: test_pricing_sync.py pins that the
    # inclusive 0.5 gate applies it without a review (4.4 / 22 → 5.5 / 33 and 4 / 20 → 5 / 30 are "changed")


# ---------------------------------------------------------------- one sync against the official sources

def _fail(*_):
    raise AssertionError("no such source in this test")


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def test_sync_verifies_the_gpt56_seeds_without_review_and_shows_the_promo_note(engine):
    labels = {k: v for family, (_, fm, *_rest) in MODELS.items() for k, v in _labels(family, fm).items()}
    active = active_channels(labels, [])
    assert sorted(m for m in active if m.startswith("openai-list:")) == [
        "openai-list:gpt-5.6-luna", "openai-list:gpt-5.6-sol", "openai-list:gpt-5.6-terra"]
    assert pricing_seed.ensure_seed(engine, active) == 9  # six channels + three OpenAI official prices
    Session = sessionmaker(bind=engine, autoflush=False)
    fixture_of = {fm: f"offers_{fk}.json" for _, fm, fk, *_rest in MODELS.values()}
    fetchers = pricing_sync.Fetchers(
        offers=lambda fm: json.loads((FIXTURES / fixture_of[fm]).read_text(encoding="utf-8")),
        pricelist=_fail, anthropic_doc=_fail,
        openai_doc=lambda: (FIXTURES / "openai_pricing_20261117.md").read_text(encoding="utf-8"))
    pricing_sync.run_sync(Session, active, fetchers, now=lambda: NOW)

    with Session() as db:
        assert db.query(models.PriceHistory).count() == 9  # no new row: every observation equals its seed
        assert db.query(models.PriceHistory).filter(models.PriceHistory.status == "pending_review").count() == 0
        current = current_rows(db, active, now=NOW)
        for mid, row in current.items():
            want = pricing_seed.seed_rows(active)[mid]
            assert (row.input_per_mtok, row.output_per_mtok) == want[:2], mid
            assert row.observed_at is not None, mid  # the sync observed the seed value, so the seed row is confirmed
        payload = build_pricing_payload(db, active, now=NOW)
    assert [f["family_key"] for f in payload["families"]] == ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]
    sol, terra, luna = payload["families"]
    assert (sol["tiers"]["global"]["input"], sol["tiers"]["global"]["output"], sol["tiers"]["openai_list"]["output"]) == (4, 20, 20)
    assert sol["tiers"]["us"] is None  # no US CRIS channel for the GPT 5.6 generation
    assert [c["regions"] for c in sol["tiers"]["in_region"]] == [["us-east-1"]]
    assert (sol["tiers"]["in_region"][0]["input"], sol["tiers"]["in_region"][0]["output"]) == (4.4, 22)
    assert terra["tiers"]["in_region"][0]["long"] == {"input": 4.4, "output": 19.8, "cache_read": 0.44, "cache_write": 5.5}
    assert (luna["tiers"]["global"]["input"], luna["tiers"]["in_region"][0]["output"]) == (0.2, 1.32)
    # the promotion note rides on GPT 5.6 Sol only, cites the OpenAI pricing reference, and the others carry none
    assert [n["kind"] for n in sol["notes"]] == ["promo"] and "2026-11-30" in sol["notes"][0]["text_en"]
    assert terra["notes"] == [] and luna["notes"] == []
    assert (sol["notes"][0]["source"], sol["notes"][0]["source_id"]) == ("openai_doc", "openai-pricing")
    assert [r["kind"] for r in payload["references"]].count("openai_doc") == 1  # one reference, cells and note share it
