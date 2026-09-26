"""단가 식별과 출처 메타데이터 (v2.30.0, ADR-030) — 55채널 정확 분류, 점 버전 안전성(2026-09-23 Opus 5.5 CP
오등록 실사고 유형), prober 등록 결과와 일치, FAMILY_ORDER = frontend sortModels.ts."""

import logging
import pathlib
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect

import models
import prober
import pricing_sources as ps
from pricing_sources import PriceIdentity, active_channels, price_identity, region_of, tier_of
from tests.pricing_catalog import ACTIVE_MODELS, CP_MODEL_IDS_20260923, EXPECTED_IDENTITY, HIDDEN_1P_MODELS

SORT_MODELS_TS = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "sortModels.ts"

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
        "source_id", "status", "observed_at", "run_id", "created_at"}
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
    active = active_channels(catalog, ["(1P)"])
    assert {m: catalog[m] for m in active} == ACTIVE_MODELS  # 라벨까지 prober 규약과 같다


def test_active_channels_hidden_and_unclassifiable(caplog):
    with caplog.at_level(logging.WARNING, logger="pricing_sources"):
        assert list(active_channels({**HIDDEN_1P_MODELS, **ACTIVE_MODELS}, ["(1P)"])) == list(ACTIVE_MODELS)
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
    assert ps.PROVIDER_ORDER == ("anthropic", "amazon", "openai")


def test_tier_of_and_region_of():
    assert [tier_of(c) for c in ("cp", "global", "us", "inregion:us-west-2")] == ["cp", "global", "us", "in_region"]
    with pytest.raises(ValueError):
        tier_of("1p")
    assert (region_of("inregion:us-east-1"), region_of("global")) == ("us-east-1", None)


def test_source_metadata_constants():
    assert ps.offer_source_id("offer-7sp77cpl4rveu") == "offer:offer-7sp77cpl4rveu"
    assert ps.pricelist_source_id("USE1-Nova2.0Lite-input-tokens") == "pricelist:USE1-Nova2.0Lite-input-tokens"
    assert ps.official_source_id("bedrock-pricing") == "official:bedrock-pricing"
    assert ps.note_source_id("gpt-5.6-sol") == "note:gpt-5.6-sol"
    assert ps.ANTHROPIC_SOURCE_ID == "anthropic-pricing"
    assert ps.ANTHROPIC_PRICING_URL == "https://platform.claude.com/docs/en/about-claude/pricing.md"
    assert (ps.OFFER_REFERENCE_URL, ps.PRICELIST_REFERENCE_URL, ps.ANTHROPIC_REFERENCE_URL) == (
        "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html",
        "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html",
        "https://platform.claude.com/docs/en/about-claude/pricing#model-pricing",
    )
    assert ps.NOVA_USAGETYPES == {"nova-2-lite": ("USE1-Nova2.0Lite-input-tokens", "USE1-Nova2.0Lite-output-tokens")}
    assert ps.ANTHROPIC_DOC_NAMES["claude-opus-5-5"] == "Claude Opus 5.5" and len(ps.ANTHROPIC_DOC_NAMES) == 9
    assert ps.EPOCH.isoformat() == "1970-01-01T00:00:00+00:00"
    assert ps.DISCLAIMER == {
        "ko": "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. "
              "최종 가격은 반드시 공식 사이트에서 확인하세요.",
        "en": "This price list is compiled automatically from public sources for reference only and is not "
              "an official AWS statement. Always confirm final prices on the official pricing pages.",
    }


def test_official_pages_and_price_notes():
    card = "https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-{}.html"
    assert [p["url"] for p in ps.OFFICIAL_PAGES] == ["https://aws.amazon.com/bedrock/pricing/"] + [
        card.format(s) for s in ("gpt-54", "gpt-55", "gpt-56-sol", "gpt-56-terra", "gpt-56-luna",
                                 "gpt-6-astra", "gpt-6-sol", "gpt-6-luna")]
    assert all(set(p) == {"slug", "title_en", "title_ko", "url"} and "·" not in p["title_ko"] for p in ps.OFFICIAL_PAGES)
    assert len({p["slug"] for p in ps.OFFICIAL_PAGES}) == 9
    (note,) = ps.PRICE_NOTES
    assert set(note) == {"family_key", "kind", "min_until", "prior_price", "text_ko", "text_en", "basis_ko", "basis_en",
                         "source"}
    assert (note["family_key"], note["kind"], note["min_until"], note["source"]) == (
        "gpt-5.6-sol", "promo", "2026-11-21", "manual_note")
    assert note["prior_price"] == {"in_region": {"input": 5.5, "output": 33}, "global": {"input": 5, "output": 30}}
    assert "2026-11-21" in note["text_ko"] and "·" not in note["text_ko"]
    assert (note["basis_ko"], note["basis_en"]) == ("2026-09-23 AWS 모델 카드 기준", "2026-09-23 AWS model card")
