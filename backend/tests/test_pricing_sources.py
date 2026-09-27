"""단가 식별과 출처 메타데이터 (v2.30.0, ADR-030) — 55채널 정확 분류, 점 버전 안전성(2026-09-23 Opus 5.5 CP
오등록 실사고 유형), prober 등록 결과와 일치, FAMILY_ORDER = frontend sortModels.ts.
v2.31.0: OpenAI 공식 가격 합성 채널(openai-list:<family_key>) 8개, OpenAI 문서 출처 상수, Nova 캐시 usagetype.
v2.31.1: OFFICIAL_PAGES 삭제(인용되지 않는 참고 자료), OFFICIAL_LINKS = frontend PricingPanel.tsx 상단 공식 요금 링크."""

import json
import logging
import pathlib
import re
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect

import models
import prober
import pricing_sources as ps
from pricing_parsers import parse_openai_pricing_md, parse_pricelist
from pricing_sources import PriceIdentity, active_channels, price_identity, region_of, tier_of
from tests.pricing_catalog import (
    ACTIVE_MODELS, CP_MODEL_IDS_20260923, EXPECTED_IDENTITY, HIDDEN_1P_MODELS, OPENAI_LIST_IDS,
)

SORT_MODELS_TS = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "sortModels.ts"
PRICING_PANEL_TSX = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "PricingPanel.tsx"
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "pricing"
OPENAI_FAMILIES = {fk: fam for fk, fam, provider, *_ in EXPECTED_IDENTITY.values() if provider == "openai"}

_ENV = {
    "ANTHROPIC_API_KEY": "sk-ant-fake", "ANTHROPIC_WORKSPACE_ID": "wrkspc_fake",  # pragma: allowlist secret
    "OPENAI_API_KEY": "ABSK-fake", "OPENAI_1P_API_KEY": "sk-proj-fake",  # pragma: allowlist secret
    "OPENAI_GLOBAL_BASE_URL": "https://gl/v1", "OPENAI_US_BASE_URL": "https://us/v1",
    "OPENAI_US_EAST_1_BASE_URL": "https://e1/v1", "OPENAI_US_EAST_2_BASE_URL": "https://e2/v1",
    "OPENAI_US_WEST_2_BASE_URL": "https://w2/v1",
    **{f"BEDROCK_OPENAI_GPT_{k}_MODEL_ID": f"openai.gpt-{v}" for k, v in (
        ("6_ASTRA", "6-astra"), ("6_SOL", "6-sol"), ("6_LUNA", "6-luna"), ("56_SOL", "5.6-sol"),
        ("56_TERRA", "5.6-terra"), ("56_LUNA", "5.6-luna"), ("54", "5.4"), ("55", "5.5"))},
    **{f"OPENAI_1P_GPT_{k}_MODEL_ID": f"gpt-{v}" for k, v in (
        ("56_SOL", "5.6-sol"), ("56_TERRA", "5.6-terra"), ("56_LUNA", "5.6-luna"), ("54", "5.4"), ("55", "5.5"))},
}


class _FakeAnthropic:
    """_discover_anthropic_models가 부르는 /v1/models만 흉내 낸다(네트워크 없음)."""

    def __init__(self, **kwargs):
        page = SimpleNamespace(data=[SimpleNamespace(id=i) for i in CP_MODEL_IDS_20260923])
        self.models = SimpleNamespace(list=lambda limit=100: page)


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "pricing_sources" and r.levelno >= logging.WARNING]


def test_create_all_creates_price_tables():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    insp = inspect(engine)
    assert {c["name"] for c in insp.get_columns("price_history")} == {
        "id", "model_id", "family_key", "channel", "input_per_mtok", "output_per_mtok", "effective_from",
        "source_id", "status", "observed_at", "run_id", "created_at",
        "cache_read_per_mtok", "cache_write_per_mtok", "cache_write_1h_per_mtok", "long_input_per_mtok",
        "long_output_per_mtok", "long_cache_read_per_mtok", "long_cache_write_per_mtok"}  # v2.31.0 표시 전용
    assert {c["name"] for c in insp.get_columns("price_sync_runs")} == {
        "id", "started_at", "finished_at", "status", "summary", "changes", "pending"}
    idx = {i["name"]: i["column_names"] for i in insp.get_indexes("price_history")}
    assert idx["ix_price_history_model_eff"] == ["model_id", "effective_from"]
    for table, cols in ((models.PriceHistory, ("effective_from", "observed_at", "created_at")),
                        (models.PriceSyncRun, ("started_at", "finished_at"))):
        assert all(table.__table__.c[c].type.timezone for c in cols)
    assert models.PriceHistory.__table__.c.observed_at.nullable is True


@pytest.mark.parametrize("model_id", sorted(EXPECTED_IDENTITY))
def test_every_real_active_model_id_is_classified(model_id):
    assert price_identity(model_id) == PriceIdentity(*EXPECTED_IDENTITY[model_id])


def test_expected_table_is_the_55_active_channels():
    counts: dict[tuple[str, str], int] = {}
    for _, _, provider, channel, _, _ in EXPECTED_IDENTITY.values():
        counts[(provider, tier_of(channel))] = counts.get((provider, tier_of(channel)), 0) + 1
    assert counts == {("anthropic", "global"): 10, ("anthropic", "us"): 10, ("anthropic", "cp"): 9,
                      ("amazon", "us"): 1, ("openai", "global"): 6, ("openai", "us"): 3, ("openai", "in_region"): 16}


def test_registered_catalog_minus_hidden_is_exactly_the_55_channels(monkeypatch):
    """prober 등록 함수를 운영 env로 실제로 돌린다 — 새 모델, 리전을 넣고 매핑을 잊으면 실패."""
    import anthropic

    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)
    for name, value in _ENV.items():
        monkeypatch.setenv(name, value)
    prober._discover_anthropic_models()
    prober._register_openai_models()
    catalog = prober.AVAILABLE_MODELS
    assert {m: lbl for m, lbl in catalog.items() if "(1P)" in lbl} == HIDDEN_1P_MODELS
    assert not any(m.startswith(ps.OPENAI_LIST_PREFIX) for m in catalog)  # 합성 id는 prober에 없다
    active = active_channels(catalog, ["(1P)"])
    listed = [m for m in active if m.startswith(ps.OPENAI_LIST_PREFIX)]
    assert {m: catalog[m] for m in active if m not in listed} == ACTIVE_MODELS  # 라벨까지 prober 규약과 같다
    assert sorted(listed) == sorted(OPENAI_LIST_IDS) and list(active)[-len(listed):] == listed  # 끝에 8개


def test_active_channels_hidden_and_unclassifiable(caplog):
    with caplog.at_level(logging.WARNING, logger="pricing_sources"):
        assert list(active_channels({**HIDDEN_1P_MODELS, **ACTIVE_MODELS}, ["(1P)"])) == list(ACTIVE_MODELS) + OPENAI_LIST_IDS
    assert _warnings(caplog) == []  # 숨김은 조용히 뺀다
    catalog = {"openai:1p:gpt-5.4": "OpenAI GPT 5.4 (1P)",
               "global.anthropic.claude-sonnet-5-5": "Bedrock Claude Sonnet 5.5 (Global)",
               "global.anthropic.claude-sonnet-5": "Bedrock Claude Sonnet 5 (Global)"}
    with caplog.at_level(logging.WARNING, logger="pricing_sources"):
        assert list(active_channels(catalog, [""])) == ["global.anthropic.claude-sonnet-5"]
    warned = " ".join(_warnings(caplog))
    assert "openai:1p:gpt-5.4" in warned and "claude-sonnet-5-5" in warned


@pytest.mark.parametrize("model_id", [
    *HIDDEN_1P_MODELS, "openai:eu-west-1:openai.gpt-5.4", "openai:global:openai.gpt-6-sol",
    "openai:us-east-1:global.openai.gpt-5.4", "openai:us-east-1:openai.gpt-6-sol-mini", "openai:global",
    "eu.anthropic.claude-opus-5", "anthropic.claude-opus-5", "us.anthropic.claude-opus-5-5-v1:0",
    "global.amazon.nova-2-lite-v1:0", "us.amazon.nova-lite-v1:0", "anthropic:claude-opus-4-6",
    "anthropic:claude-opus-4-5-20251101", "anthropic:claude-sonnet-4-5-20250929", "anthropic:claude-mythos-5-1", "",
    # the prefix is checked, not just its length ("global." is 7 characters, "us." is 3)
    "openai:global:xxxxxxxopenai.gpt-6-sol", "openai:us:xxxopenai.gpt-6-astra",
    # OpenAI official price ids: exact family keys of the eight Bedrock GPT families only
    "openai-list:", "openai-list:gpt-5.4-mini", "openai-list:gpt-5.4-pro", "openai-list:openai.gpt-5.4",
    "openai-list:GPT-5.4", "openai-list:gpt-5.4 ", "openai-list:claude-opus-5-5", "openai-list:nova-2-lite",
    "openai_list:gpt-5.4", "openai:list:gpt-5.4",
])
def test_unclassifiable_model_ids_return_none(model_id):
    assert price_identity(model_id) is None


def test_cp_point_release_safety():
    fk = {m: price_identity(f"anthropic:{m}") for m in (
        "claude-opus-5", "claude-opus-5-5", "claude-fable-5", "claude-fable-5-1", "claude-haiku-4-5-20251001",
        "claude-opus-5-20261015", "claude-fable-5-1-20261015", "claude-sonnet-5-5", "claude-opus-5-6")}
    assert {m: (i.family_key if i else None) for m, i in fk.items()} == {
        "claude-opus-5": "claude-opus-5", "claude-opus-5-5": "claude-opus-5-5",
        "claude-fable-5": "claude-fable-5", "claude-fable-5-1": "claude-fable-5-1",
        "claude-haiku-4-5-20251001": "claude-haiku-4-5",  # 8자리 날짜 접미사는 점 버전이 아니다
        "claude-opus-5-20261015": "claude-opus-5", "claude-fable-5-1-20261015": "claude-fable-5-1",
        "claude-sonnet-5-5": None, "claude-opus-5-6": None,  # 타깃 없는 점 버전은 fail-closed
    }
    assert price_identity("global.anthropic.claude-sonnet-5-5") is None


def test_cp_family_key_does_not_depend_on_target_order(monkeypatch):
    """The longer target wins because shorter ones yield to it, not because it is listed first."""
    monkeypatch.setattr(ps, "_CP_TARGETS", tuple(reversed(ps._CP_TARGETS)))
    assert ps._CP_TARGETS.index("opus-5") < ps._CP_TARGETS.index("opus-5-5")  # the shorter one is tried first
    assert ps._cp_family_key("claude-opus-5-5") == "claude-opus-5-5"
    assert ps._cp_family_key("claude-fable-5-1-20261015") == "claude-fable-5-1"
    assert ps._cp_family_key("claude-opus-5") == "claude-opus-5"


@pytest.mark.parametrize("actual_id", [
    *CP_MODEL_IDS_20260923, "claude-sonnet-5-5", "claude-opus-5-6", "claude-fable-5-2",
    "claude-opus-5-20261015", "claude-fable-5-1-20261015", "claude-haiku-4-5", "claude-sonnet-4-6-20260101",
])
def test_cp_classification_agrees_with_prober_matching(actual_id):
    ident = price_identity(f"anthropic:{actual_id}")
    hits = [s for s, _ in prober._ANTHROPIC_TARGETS if prober._match_anthropic_model(s, [actual_id]) == actual_id]
    assert (ident.family_key if ident else None) == (f"claude-{hits[0]}" if hits else None)


def test_cp_targets_and_static_labels_mirror_prober():
    assert [fk.removeprefix("claude-") for fk in ps.ANTHROPIC_DOC_NAMES] == [s for s, _ in prober._ANTHROPIC_TARGETS]
    for sub, label in prober._ANTHROPIC_TARGETS:
        assert label == f"Anthropic {price_identity(f'anthropic:claude-{sub}').family} (US)"
    for model_id, label in prober.AVAILABLE_MODELS.items():
        if model_id.startswith(("anthropic:", "openai:")):
            continue  # 런타임 등록 채널은 위 등록 테스트가 본다
        ident = price_identity(model_id)
        assert label == f"Bedrock {ident.family} ({'Global' if ident.channel == 'global' else 'US'})", model_id


def test_family_order_matches_frontend_sort_models():
    m = re.search(r"export const FAMILY_ORDER = \[(.*?)\];", SORT_MODELS_TS.read_text(encoding="utf-8"), re.S)
    assert m and ps.FAMILY_ORDER == tuple(re.findall(r'"([^"]+)"', m.group(1)))
    assert len(ps.FAMILY_ORDER) == 19
    assert {v[1] for v in EXPECTED_IDENTITY.values()} == set(ps.FAMILY_ORDER)
    assert ps.PROVIDER_ORDER == ("anthropic", "openai", "amazon")


def test_tier_of_and_region_of():
    assert [tier_of(c) for c in ("cp", "openai_list", "global", "us", "inregion:us-west-2")] == [
        "cp", "openai_list", "global", "us", "in_region"]
    with pytest.raises(ValueError):
        tier_of("1p")
    assert (region_of("inregion:us-east-1"), region_of("global"), region_of("openai_list")) == ("us-east-1", None, None)


@pytest.mark.parametrize("family_key", list(OPENAI_FAMILIES))
def test_openai_list_ids_are_classified(family_key):
    model_id = ps.openai_list_model_id(family_key)
    assert model_id == f"openai-list:{family_key}"
    assert price_identity(model_id) == PriceIdentity(
        family_key, OPENAI_FAMILIES[family_key], "openai", "openai_list", "openai_doc", family_key)


def test_openai_list_ids_are_the_eight_bedrock_gpt_families_and_rows_of_the_openai_doc():
    assert OPENAI_LIST_IDS == [ps.openai_list_model_id(fk) for fk in OPENAI_FAMILIES] and len(OPENAI_LIST_IDS) == 8
    prices = parse_openai_pricing_md((FIXTURES / "openai_pricing.md").read_text(encoding="utf-8"))
    assert all(price_identity(m).source_ref in prices for m in OPENAI_LIST_IDS)  # exact doc model names


def test_active_channels_appends_one_openai_list_channel_per_visible_openai_family(caplog):
    models = {
        "openai:us-east-1:openai.gpt-5.4": "OpenAI GPT 5.4 (us-east-1)",
        "global.anthropic.claude-opus-5-5": "Bedrock Claude Opus 5.5 (Global)",
        "openai:global:global.openai.gpt-6-sol": "OpenAI GPT 6 Sol (Global)",
        "openai:us-east-2:openai.gpt-5.4": "OpenAI GPT 5.4 (us-east-2)",
        "us.amazon.nova-2-lite-v1:0": "Bedrock Nova 2.0 Lite (US)",
        "openai:us-east-1:openai.gpt-5.5": "OpenAI GPT 5.5 (us-east-1)",
    }
    with caplog.at_level(logging.WARNING, logger="pricing_sources"):
        active = active_channels(models, ["(us-east-1)"])
    assert list(active) == [
        "global.anthropic.claude-opus-5-5", "openai:global:global.openai.gpt-6-sol", "openai:us-east-2:openai.gpt-5.4",
        "us.amazon.nova-2-lite-v1:0", "openai-list:gpt-6-sol", "openai-list:gpt-5.4",  # GPT 5.5 is hidden: none
    ]
    assert active["openai-list:gpt-5.4"].channel == "openai_list" and _warnings(caplog) == []
    again = active_channels({"openai-list:gpt-5.4": "OpenAI GPT 5.4 (official)", **models}, [])
    assert [m for m in again if m.startswith("openai-list:")] == [
        "openai-list:gpt-5.4", "openai-list:gpt-6-sol", "openai-list:gpt-5.5"]  # an id already present is kept once
    no_openai = active_channels({"global.anthropic.claude-opus-5-5": "a", "us.amazon.nova-2-lite-v1:0": "b"}, [])
    assert list(no_openai) == ["global.anthropic.claude-opus-5-5", "us.amazon.nova-2-lite-v1:0"]


def test_source_metadata_constants():
    assert ps.offer_source_id("offer-7sp77cpl4rveu") == "offer:offer-7sp77cpl4rveu"
    assert ps.pricelist_source_id("USE1-Nova2.0Lite-input-tokens") == "pricelist:USE1-Nova2.0Lite-input-tokens"
    assert ps.note_source_id("gpt-5.6-sol") == "note:gpt-5.6-sol"
    assert ps.ANTHROPIC_SOURCE_ID == "anthropic-pricing"
    assert ps.ANTHROPIC_PRICING_URL == "https://platform.claude.com/docs/en/about-claude/pricing.md"
    assert (ps.OFFER_REFERENCE_URL, ps.PRICELIST_REFERENCE_URL, ps.ANTHROPIC_REFERENCE_URL) == (
        "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html",
        "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html",
        "https://platform.claude.com/docs/en/about-claude/pricing#model-pricing",
    )
    assert ps.NOVA_USAGETYPES == {"nova-2-lite": ("USE1-Nova2.0Lite-input-tokens", "USE1-Nova2.0Lite-output-tokens")}
    assert ps.NOVA_CACHE_USAGETYPES == {"nova-2-lite": (
        "USE1-Nova2.0Lite-cache-read-input-token-count", "USE1-Nova2.0Lite-cache-write-input-token-count")}
    assert (ps.OPENAI_PRICING_URL, ps.OPENAI_SOURCE_ID, ps.OPENAI_REFERENCE_URL, ps.OPENAI_LIST_PREFIX) == (
        "https://developers.openai.com/api/docs/pricing.md", "openai-pricing",
        "https://developers.openai.com/api/docs/pricing", "openai-list:",
    )
    assert ps.ANTHROPIC_DOC_NAMES["claude-opus-5-5"] == "Claude Opus 5.5" and len(ps.ANTHROPIC_DOC_NAMES) == 9
    assert ps.EPOCH.isoformat() == "1970-01-01T00:00:00+00:00"
    assert ps.DISCLAIMER == {
        "ko": "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. "
              "최종 가격은 반드시 공식 사이트에서 확인하세요.",
        "en": "This price list is compiled automatically from public sources for reference only and is not "
              "an official AWS statement. Always confirm final prices on the official pricing pages.",
    }


def test_nova_cache_usagetypes_read_the_price_list_fixture():
    items = json.loads((FIXTURES / "pricelist_nova-2-lite.json").read_text(encoding="utf-8"))["PriceList"]
    price = parse_pricelist(items, *ps.NOVA_USAGETYPES["nova-2-lite"], *ps.NOVA_CACHE_USAGETYPES["nova-2-lite"])
    assert (price.input, price.output, price.cache_read, price.cache_write) == (
        Decimal("0.33"), Decimal("2.75"), Decimal("0.0825"), Decimal(0))
    assert set(ps.NOVA_CACHE_USAGETYPES) == set(ps.NOVA_USAGETYPES)


def test_official_links_matches_frontend_pricing_panel():
    """The Markdown header links = the screen's top box (PricingPanel.tsx OFFICIAL_LINKS), same order."""
    m = re.search(r"const OFFICIAL_LINKS[^=]*= \[(.*?)\];", PRICING_PANEL_TSX.read_text(encoding="utf-8"), re.S)
    assert m
    entries = re.findall(r'\{\s*url: "([^"]+)",\s*en: "([^"]+)",\s*ko: "([^"]+)"\s*\}', m.group(1))
    assert len(entries) == 3
    assert [(link["url"], link["title_en"], link["title_ko"]) for link in ps.OFFICIAL_LINKS] == entries


def test_official_links_and_price_notes():
    assert ps.OFFICIAL_LINKS == [
        {"title_en": "Amazon Bedrock pricing", "title_ko": "Amazon Bedrock 요금",
         "url": "https://aws.amazon.com/bedrock/pricing/"},
        {"title_en": "Anthropic pricing", "title_ko": "Anthropic 요금",
         "url": "https://platform.claude.com/docs/en/about-claude/pricing"},
        {"title_en": "OpenAI pricing", "title_ko": "OpenAI 요금", "url": "https://developers.openai.com/api/docs/pricing"},
    ]
    # v2.31.1: references list only cited sources — the fixed official pages are gone
    assert not hasattr(ps, "OFFICIAL_PAGES") and not hasattr(ps, "official_source_id")
    (note,) = ps.PRICE_NOTES
    assert set(note) == {"family_key", "kind", "min_until", "prior_price", "text_ko", "text_en", "source", "source_id"}
    assert (note["family_key"], note["kind"], note["min_until"], note["source"], note["source_id"]) == (
        "gpt-5.6-sol", "promo", "2026-11-21", "openai_doc", "openai-pricing")
    assert note["source_id"] == ps.OPENAI_SOURCE_ID
    assert note["prior_price"] == {"openai_list": {"input": 5, "output": 30}, "global": {"input": 5, "output": 30},
                                   "in_region": {"input": 5.5, "output": 33}}
    # dated: the sync never re-reads this sentence, so the note says when it was read (2026-09-27)
    assert note["text_ko"] == "프로모션 단가다. 2026-09-27 기준 OpenAI 공식 요금 문서에 최소 2026-11-21까지 적용한다고 기재돼 있다."
    assert note["text_en"] == (
        "Promotional price. As of 2026-09-27, the OpenAI pricing page states that it applies at least through 2026-11-21.")
    assert "·" not in note["text_ko"]
