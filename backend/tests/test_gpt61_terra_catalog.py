"""OpenAI GPT 6.1 Terra 편입과 Mantle 인리전 us-east-1 일원화 (v2.38.0, ADR-033).

2026-10-27 실측(운영 Bedrock 장기 키, Responses API 스트리밍):
  - GPT 6.1 Terra: Global CRIS(Seoul bedrock-runtime) 200, US CRIS(us-east-1 bedrock-runtime) 200, Mantle us-east-1은
    첫 호출 401 "subscription is being set up" 뒤 약 2분 만에 200, Mantle us-east-2와 us-west-2는 404 not_found_error.
    패리티 reasoning 프로브 형태(effort low, "17 x 23은?")에서 reasoning_tokens 0(Responses, Chat Completions 각 3회).
  - 같은 날 Mantle us-east-1이 모니터링하는 GPT 10개 모델을 모두 서빙(200) — GPT 6 Astra 포함(2026-09-09·09-23 404).
  - 사용자 결정 "gpt mantle은 모두 us-east-1으로 변경": Mantle 인리전 채널은 모델마다 us-east-1 하나.
  - 오퍼 offer-34pzbdgg26ley: In-Region과 Geo CRIS $1.10/$5.50, Global $1/$5. 긴 컨텍스트 출력(8.25 / 7.5)이 짧은
    컨텍스트 출력보다 높아 정상값이다(GPT 6.1 Sol 오퍼는 낮아서 버린다).
"""

import logging
import pathlib

import pytest

import gptbench
import prober
from parity.catalog import is_reasoning_capable
from pricing_parsers import parse_openai_pricing_md
from pricing_seed import OPENAI_LIST_SEED, SEED, seed_extra
from pricing_sources import price_identity
from pricing_sync import _plausible_long

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "pricing"

_TERRA_KEYS = [
    "openai:global:global.openai.gpt-6.1-terra",
    "openai:us:us.openai.gpt-6.1-terra",
    "openai:us-east-1:openai.gpt-6.1-terra",
]
_BASE_URLS = (
    ("OPENAI_GLOBAL_BASE_URL", "https://gl/openai/v1"),
    ("OPENAI_US_BASE_URL", "https://us/openai/v1"),
    ("OPENAI_US_EAST_1_BASE_URL", "https://e1/openai/v1"),
    ("OPENAI_US_EAST_2_BASE_URL", "https://e2/openai/v1"),
    ("OPENAI_US_WEST_2_BASE_URL", "https://w2/openai/v1"),
)
_MODEL_ENV = {
    "BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID": "openai.gpt-6.1-sol",
    "BEDROCK_OPENAI_GPT_61_TERRA_MODEL_ID": "openai.gpt-6.1-terra",
    "BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID": "openai.gpt-6-astra",
    "BEDROCK_OPENAI_GPT_6_SOL_MODEL_ID": "openai.gpt-6-sol",
    "BEDROCK_OPENAI_GPT_6_LUNA_MODEL_ID": "openai.gpt-6-luna",
    "BEDROCK_OPENAI_GPT_56_SOL_MODEL_ID": "openai.gpt-5.6-sol",
    "BEDROCK_OPENAI_GPT_56_TERRA_MODEL_ID": "openai.gpt-5.6-terra",
    "BEDROCK_OPENAI_GPT_56_LUNA_MODEL_ID": "openai.gpt-5.6-luna",
    "BEDROCK_OPENAI_GPT_55_MODEL_ID": "openai.gpt-5.5",
}


def _register(monkeypatch, model_env):
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.delenv("OPENAI_1P_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    for env, url in _BASE_URLS:
        monkeypatch.setenv(env, url)
    for env in _MODEL_ENV:
        monkeypatch.delenv(env, raising=False)
    for env, value in model_env.items():
        monkeypatch.setenv(env, value)
    prober._register_openai_models()
    return {k: v for k, v in prober.AVAILABLE_MODELS.items() if k.startswith("openai:")}


# ---------------------------------------------------------------- GPT 6.1 Terra

def test_gpt61_terra_spec_follows_gpt61_sol():
    assert prober._OPENAI_MODEL_SPECS[:2] == [
        ("BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID", "GPT 6.1 Sol", ("global", "us", "us-east-1")),
        ("BEDROCK_OPENAI_GPT_61_TERRA_MODEL_ID", "GPT 6.1 Terra", ("global", "us", "us-east-1")),
    ]


def test_gpt61_terra_registers_exactly_three_channels(monkeypatch):
    """Global CRIS + US CRIS + Mantle us-east-1 — us-east-2/us-west-2는 base URL env가 있어도 미등록(404)."""
    openai = _register(monkeypatch, {"BEDROCK_OPENAI_GPT_61_TERRA_MODEL_ID": "openai.gpt-6.1-terra"})
    assert sorted(openai) == sorted(_TERRA_KEYS)
    # 라벨은 DB model_name에 영구 기록 — frontend MODEL_COLORS 키와 바이트 단위로 일치해야 함.
    assert openai == {
        "openai:global:global.openai.gpt-6.1-terra": "OpenAI GPT 6.1 Terra (Global)",
        "openai:us:us.openai.gpt-6.1-terra": "OpenAI GPT 6.1 Terra (US)",
        "openai:us-east-1:openai.gpt-6.1-terra": "OpenAI GPT 6.1 Terra (us-east-1)",
    }


def test_gpt61_terra_is_skipped_without_its_model_id_env(monkeypatch):
    # env 누락이면 3채널이 조용히 빠진다 — CDK가 두 스택 모두에 주입해야 하는 이유.
    openai = _register(monkeypatch, {"BEDROCK_OPENAI_GPT_61_SOL_MODEL_ID": "openai.gpt-6.1-sol"})
    assert not [k for k in openai if "gpt-6.1-terra" in k]


def test_gpt61_terra_does_not_collide_with_other_family_markers():
    for key in _TERRA_KEYS:
        assert "gpt-6.1-sol" not in key and "gpt-5.6-terra" not in key and "gpt-5" not in key
        assert is_reasoning_capable(key) is False  # effort low reasoning_tokens 0 (2026-10-27)


def test_gpt61_terra_price_identity_and_seed():
    for key in _TERRA_KEYS:
        ident = price_identity(key)
        assert (ident.family_key, ident.family, ident.provider, ident.source_kind, ident.source_ref) == (
            "gpt-6.1-terra", "GPT 6.1 Terra", "openai", "offer", "openai.gpt-6.1-terra"), key
    assert SEED["openai:global:global.openai.gpt-6.1-terra"] == (1.0, 5.0, "offer:offer-34pzbdgg26ley")
    assert SEED["openai:us:us.openai.gpt-6.1-terra"] == (1.1, 5.5, "offer:offer-34pzbdgg26ley")
    assert SEED["openai:us-east-1:openai.gpt-6.1-terra"] == (1.1, 5.5, "offer:offer-34pzbdgg26ley")
    assert OPENAI_LIST_SEED["gpt-6.1-terra"] == (1.0, 5.0, "openai-pricing")
    ident = price_identity("openai-list:gpt-6.1-terra")
    assert (ident.channel, ident.source_kind, ident.source_ref) == ("openai_list", "openai_doc", "gpt-6.1-terra")


def test_gpt61_terra_seed_keeps_its_plausible_long_context(caplog):
    """Unlike the 6.1 Sol offer, the Terra offer's long-context output is above the short one — nothing is dropped."""
    from pricing_parsers import UnitPrice

    extras = seed_extra("openai:us-east-1:openai.gpt-6.1-terra", price_identity("openai:us-east-1:openai.gpt-6.1-terra"))
    assert (extras["long_input"], extras["long_output"]) == (2.2, 8.25)
    price = UnitPrice(input=1.1, output=5.5, long_input=2.2, long_output=8.25, long_cache_read=0.11,
                      long_cache_write=2.75)
    with caplog.at_level(logging.WARNING, logger="pricing_sync"):
        assert _plausible_long(price, "openai.gpt-6.1-terra") == price
    assert caplog.messages == []


def test_openai_doc_of_20261027_lists_gpt61_terra():
    """The 2026-10-27 OpenAI pricing doc: Terra's Standard row gives the seeded input, output, cache read and long
    context. Its header renamed "cache writes" to "30m write" / "12h write", so the parser leaves both cache-write
    fields None there (the stored seed value is kept — a None observation is not a change)."""
    prices = parse_openai_pricing_md((FIXTURES / "openai_pricing_20261027.md").read_text(encoding="utf-8"))
    terra = prices["gpt-6.1-terra"]
    assert tuple(float(v) for v in (terra.input, terra.output, terra.cache_read, terra.long_input, terra.long_output,
                                    terra.long_cache_read)) == (1.0, 5.0, 0.05, 2.0, 7.5, 0.1)
    assert (terra.cache_write, terra.long_cache_write) == (None, None)


# ---------------------------------------------------------------- Mantle 인리전 us-east-1 일원화

def test_every_mantle_in_region_channel_is_us_east_1(monkeypatch):
    openai = _register(monkeypatch, _MODEL_ENV)
    in_region = sorted(k for k in openai if k.split(":")[1] not in prober._OPENAI_PSEUDO_REGIONS)
    assert in_region == sorted(f"openai:us-east-1:{fm}" for fm in _MODEL_ENV.values())  # 모델마다 정확히 하나
    assert not [k for k in openai if k.startswith(("openai:us-east-2:", "openai:us-west-2:"))]
    assert len(openai) == 22  # Mantle us-east-1 9 + Global CRIS 8 + US CRIS 5 (v2.39.0 — GPT 5.4 left; 23 in v2.38.0)


def test_gpt6_astra_in_region_channel_moved_to_us_east_1(monkeypatch):
    openai = _register(monkeypatch, {"BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID": "openai.gpt-6-astra"})
    assert openai["openai:us-east-1:openai.gpt-6-astra"] == "OpenAI GPT 6 Astra (us-east-1)"
    assert "openai:us-west-2:openai.gpt-6-astra" not in openai


def test_bench_keeps_one_mantle_lane_and_appends_gpt61_terra(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "ABSK-fake")
    for env, url in _BASE_URLS:
        monkeypatch.setenv(env, url)
    for env, value in _MODEL_ENV.items():
        monkeypatch.setenv(env, value)
    chans = gptbench.bench_channels()
    assert [c["model_id"] for c in chans][-3:] == [
        "openai:global:global.openai.gpt-6.1-terra", "openai:us:us.openai.gpt-6.1-terra",
        "openai:us-east-1:openai.gpt-6.1-terra"]
    lanes = gptbench.bench_lanes(chans)
    assert {lane: len(items) for lane, items in lanes.items()} == {"cris": 11, "mantle-us-east-1": 7}  # 8 in v2.38.0


@pytest.mark.parametrize("region", ["us-east-2", "us-west-2"])
def test_no_bench_spec_names_a_dropped_mantle_region(region):
    assert all(region not in regions for _, _, regions in gptbench._BENCH_SPECS)
