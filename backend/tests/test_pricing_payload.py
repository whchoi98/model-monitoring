"""pricing_payload.build_pricing_payload — exact /api/pricing JSON on a small golden dataset (v2.30.0, v2.31.0).

Dataset (tests/_pricing_dataset.py): Claude Opus 5.5 on three channels with prompt-caching prices, a stale Nova
row whose cache write is exactly 0, GPT 6 Luna with no price rows, GPT 5.6 Sol with two pending rows on its
Global channel, a seed-only in-region row and an OpenAI-doc promo note, GPT 5.6 Terra whose us-west-2 price
differs from us-east-1/us-east-2, GPT 5.5 seed-only, GPT 5.4 on three equal regions plus its OpenAI official
price (openai_list), and rows for inactive model_ids that must never appear. OFFICIAL_PAGES and PRICE_NOTES are
pinned to test copies so the golden does not depend on their production wording; DISCLAIMER is the spec text.
"""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import pricing_sources
from pricing_payload import build_pricing_payload, price_number, price_number_or_none, price_text
from pricing_sources import price_identity
from tests import _pricing_dataset as ds
from tests._pricing_dataset import EXPECTED_PAYLOAD, G54, G55, NOVA, OPUS, SOL, TERRA

TIER_ORDER = ["cp", "openai_list", "global", "us", "in_region"]
CELL_PRICE_KEYS = {"input", "output", "cache_read", "cache_write", "cache_write_1h", "long"}


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setattr(pricing_sources, "OFFICIAL_PAGES", ds.OFFICIAL_PAGES)
    monkeypatch.setattr(pricing_sources, "PRICE_NOTES", [ds.SOL_NOTE])
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    ds.load(session)
    yield session
    session.close()
    engine.dispose()


def _cells(family):
    tiers = family["tiers"]
    return [tiers[t] for t in ("cp", "openai_list", "global", "us") if tiers[t]] + tiers["in_region"]


def _family(payload, family_key):
    return next(f for f in payload["families"] if f["family_key"] == family_key)


def test_payload_matches_the_golden_exactly(db):
    assert build_pricing_payload(db, ds.active(), now=ds.NOW) == EXPECTED_PAYLOAD


def test_families_follow_provider_order_anthropic_openai_amazon(db):
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    assert pricing_sources.PROVIDER_ORDER == ("anthropic", "openai", "amazon")
    assert [f["provider"] for f in payload["families"]] == ["anthropic"] + ["openai"] * 5 + ["amazon"]


def test_tiers_always_have_five_keys_in_display_order(db):
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    for family in payload["families"]:
        assert list(family["tiers"]) == TIER_ORDER
        assert isinstance(family["tiers"]["in_region"], list)
    assert _family(payload, "gpt-5.4")["tiers"]["openai_list"]["model_ids"] == ["openai-list:gpt-5.4"]
    assert _family(payload, "claude-opus-5-5")["tiers"]["openai_list"] is None


def test_every_cell_and_pending_object_carries_the_extra_price_keys(db):
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    for family in payload["families"]:
        for cell in _cells(family):
            assert CELL_PRICE_KEYS <= set(cell)
            if cell["long"] is not None:
                assert set(cell["long"]) == {"input", "output", "cache_read", "cache_write"}
            if cell["pending"] is not None:
                assert set(cell["pending"]) == CELL_PRICE_KEYS | {"id", "observed_at"}
    nova = _family(payload, "nova-2-lite")["tiers"]["us"]
    assert (nova["cache_read"], nova["cache_write"], nova["cache_write_1h"], nova["long"]) == (0.0825, 0, None, None)
    assert isinstance(nova["cache_write"], int)  # an official $0.00 stays 0, it is not dropped as missing


def test_models_leave_out_the_display_only_openai_list_channels(db):
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    assert "openai-list:gpt-5.4" not in payload["models"]
    assert set(payload["models"]) == {
        mid for mid in ds.ACTIVE_IDS if not mid.startswith("openai-list:") and mid != "openai:global:global.openai.gpt-6-luna"}


def test_every_footnote_resolves_to_the_cited_source(db):
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    refs = {r["n"]: r["id"] for r in payload["references"]}
    assert sorted(refs) == list(range(1, len(refs) + 1))
    for family in payload["families"]:
        for cell in _cells(family):
            assert [refs[n] for n in cell["footnotes"]] == cell["source_ids"]
        for note in family["notes"]:
            assert note["source_id"] in refs.values()


def test_numbers_serialize_without_trailing_zeros():
    assert price_number(4.0) == 4 and isinstance(price_number(4.0), int)
    assert price_number(4.40) == 4.4
    assert price_number(4.0 * 1.1) == 4.4  # 4.4000000000000004
    assert price_number(0.1234567) == 0.123457
    assert price_text(4.4) == "4.4"
    assert price_text(0.11) == "0.11"
    assert price_text(20.0) == "20"
    assert price_text(0.00001) == "0.00001"
    assert price_number_or_none(None) is None
    assert price_number_or_none(0.0) == 0 and isinstance(price_number_or_none(0.0), int)
    assert price_number_or_none(0.0825) == 0.0825


def test_equal_input_output_with_a_different_cache_price_forms_its_own_in_region_element(db):
    ds.add_price(db, "openai:us-west-2:openai.gpt-5.4", 2.75, 16.5, effective_from=ds.RUN2, status="verified",
                 observed_at=ds.RUN2, source_id=G54, **{**ds.G54_STANDARD_EXTRA, "cache_read": 0.3})
    db.commit()
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    elements = _family(payload, "gpt-5.4")["tiers"]["in_region"]
    assert [(e["regions"], e["input"], e["output"], e["cache_read"]) for e in elements] == [
        (["us-east-1", "us-east-2"], 2.75, 16.5, 0.275), (["us-west-2"], 2.75, 16.5, 0.3)]


def test_a_pending_value_that_differs_only_in_an_extra_field_splits_the_group(db):
    ds.add_price(db, "openai:us-east-2:openai.gpt-5.4", 2.75, 16.5, effective_from=ds.RUN2,
                 status="pending_review", observed_at=ds.RUN2, source_id=G54,
                 **{**ds.G54_STANDARD_EXTRA, "cache_read": 0.3})
    db.commit()
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    elements = _family(payload, "gpt-5.4")["tiers"]["in_region"]
    assert [e["regions"] for e in elements] == [["us-east-1", "us-west-2"], ["us-east-2"]]
    assert elements[0]["pending"] is None
    assert (elements[1]["pending"]["input"], elements[1]["pending"]["cache_read"]) == (2.75, 0.3)
    assert payload["pending_review"] == 2


def test_a_cell_without_long_input_and_output_has_long_null(db):
    ds.add_price(db, "openai:us-east-1:openai.gpt-5.5", 5.5, 33.0, effective_from=ds.RUN2, status="verified",
                 observed_at=ds.RUN2, source_id=G55, cache_read=0.55, long_input=11.0, long_cache_read=1.1)
    db.commit()
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    (element,) = _family(payload, "gpt-5.5")["tiers"]["in_region"]
    assert (element["cache_read"], element["long"]) == (0.55, None)  # long_output missing -> no long object


def test_openai_doc_note_cites_its_source_right_after_the_family_cells(db):
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    ids = [r["id"] for r in payload["references"]]
    # Sol cells cite SOL (3); the Sol note then cites openai-pricing (4) before Terra's offer (5).
    assert ids[:8] == ["anthropic-pricing", OPUS, SOL, "openai-pricing", TERRA, G55, G54, NOVA]
    ref = payload["references"][3]
    assert {k: ref[k] for k in ("kind", "title_en", "title_ko", "url")} == {
        "kind": "openai_doc", "title_en": "OpenAI API pricing (Standard)", "title_ko": "OpenAI API 요금 (Standard)",
        "url": "https://developers.openai.com/api/docs/pricing"}
    assert _family(payload, "gpt-5.4")["tiers"]["openai_list"]["footnotes"] == [4]


def test_promo_note_drops_once_the_prior_price_is_observed(db):
    ds.add_price(db, "openai:us-east-1:openai.gpt-5.6-sol", 5.5, 33.0, effective_from=ds.RUN2, status="verified",
                 observed_at=ds.RUN2, source_id=SOL)
    db.commit()
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    assert _family(payload, "gpt-5.6-sol")["notes"] == []
    # without the note, openai-pricing is first cited by the GPT 5.4 openai_list cell
    ids = [r["id"] for r in payload["references"]]
    assert ids[:8] == ["anthropic-pricing", OPUS, SOL, TERRA, G55, "openai-pricing", G54, NOVA]
    assert "manual_note" not in [r["kind"] for r in payload["references"]]


def test_promo_note_drops_once_the_openai_list_tier_shows_the_prior_price(db):
    ds.add_price(db, "openai-list:gpt-5.6-sol", 5.0, 30.0, observed_at=ds.RUN2, source_id="openai-pricing")
    db.commit()
    active = {**ds.active(), "openai-list:gpt-5.6-sol": price_identity("openai-list:gpt-5.6-sol")}
    payload = build_pricing_payload(db, active, now=ds.NOW)
    sol = _family(payload, "gpt-5.6-sol")
    assert (sol["tiers"]["openai_list"]["input"], sol["tiers"]["openai_list"]["output"]) == (5, 30)
    assert sol["notes"] == []


def test_manual_note_keeps_its_reference_after_the_official_pages(db, monkeypatch):
    note = {**ds.MANUAL_NOTE, "family_key": "gpt-5.4", "prior_price": {}}
    monkeypatch.setattr(pricing_sources, "PRICE_NOTES", [note])
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    assert payload["references"][-1] == {
        "n": 11, "id": "note:gpt-5.4", "kind": "manual_note",
        "title_en": "GPT 5.4 promotion (manual note, 2026-09-23 AWS model card)",
        "title_ko": "GPT 5.4 프로모션 (수동 메모, 2026-09-23 AWS 모델 카드 기준)", "url": None, "as_of": None}
    assert [r["kind"] for r in payload["references"]][-3:] == ["official_page", "official_page", "manual_note"]
    (payload_note,) = _family(payload, "gpt-5.4")["notes"]
    assert payload_note == {
        "family_key": "gpt-5.4", "kind": "promo", "min_until": "2026-11-21", "prior_price": {},
        "text_ko": "프로모션 단가, 최소 2026-11-21까지", "text_en": "Promotional price, at least until 2026-11-21",
        "source": "manual_note", "source_id": "note:gpt-5.4"}  # basis fields never leave the backend
    # a manual note is numbered at the end, never through the cell citations
    assert "note:gpt-5.4" not in [s for f in payload["families"] for c in _cells(f) for s in c["source_ids"]]


def test_price_rows_effective_after_now_are_not_current_yet(db):
    ds.add_price(db, "us.anthropic.claude-opus-5-5", 5.0, 25.0, effective_from=ds.NOW + timedelta(hours=1),
                 status="verified", observed_at=ds.NOW, source_id=OPUS)
    db.commit()
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    assert payload["models"]["us.anthropic.claude-opus-5-5"]["input"] == 4.4


def test_empty_active_set_still_returns_the_fixed_sections(db):
    payload = build_pricing_payload(db, {}, now=ds.NOW)
    assert payload["families"] == [] and payload["models"] == {} and payload["pending_review"] == 0
    assert [r["kind"] for r in payload["references"]] == ["official_page", "official_page"]


def test_production_official_pages_and_note_are_listed_after_the_cited_sources(db, monkeypatch):
    monkeypatch.undo()  # production OFFICIAL_PAGES and PRICE_NOTES
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    kinds = [r["kind"] for r in payload["references"]]
    cited = sum(kinds.count(k) for k in ("agreement_offer", "price_list", "anthropic_doc", "openai_doc"))
    assert kinds[cited:] == ["official_page"] * 9
    assert {r["url"] for r in payload["references"] if r["kind"] == "official_page"} == {
        "https://aws.amazon.com/bedrock/pricing/",
        *(f"https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-{slug}.html" for slug in (
            "gpt-54", "gpt-55", "gpt-56-sol", "gpt-56-terra", "gpt-56-luna", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna")),
    }
    sol = _family(payload, "gpt-5.6-sol")
    (note,) = sol["notes"]
    assert set(note) == {"family_key", "kind", "min_until", "prior_price", "text_ko", "text_en", "source", "source_id"}
    assert (note["source"], note["source_id"]) == ("openai_doc", "openai-pricing")
    ref = next(r for r in payload["references"] if r["id"] == "openai-pricing")
    assert (ref["n"], ref["kind"], ref["url"]) == (4, "openai_doc", "https://developers.openai.com/api/docs/pricing")
