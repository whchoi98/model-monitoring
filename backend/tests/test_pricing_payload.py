"""pricing_payload.build_pricing_payload — exact /api/pricing JSON on a small golden dataset (v2.30.0, v2.31.0).

Dataset (tests/_pricing_dataset.py): Claude Opus 5.5 on three channels with prompt-caching prices, a stale Nova
row whose cache write is exactly 0, GPT 6 Luna with no price rows, GPT 5.6 Sol with two pending rows on its
Global channel, a seed-only in-region row and an OpenAI-doc promo note, GPT 5.6 Terra whose us-west-2 price
differs from us-east-1/us-east-2, GPT 5.5 seed-only, GPT 5.4 on three equal regions plus its OpenAI official
price (openai_list), and rows for inactive model_ids that must never appear. PRICE_NOTES is pinned to a test
copy so the golden does not depend on its production wording; DISCLAIMER is the spec text. References list only
cited sources (v2.31.1): the invariant test at the bottom builds the payload on the real seeds of the 55 active
channels (tests/pricing_catalog.py) and checks that every reference is cited.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import pricing_seed
import pricing_sources
from pricing_payload import build_pricing_payload, price_number, price_number_or_none, price_text
from pricing_sources import active_channels, price_identity
from tests import _pricing_dataset as ds
from tests._pricing_dataset import EXPECTED_PAYLOAD, G54, G55, NOVA, OPUS, SOL, TERRA
from tests.pricing_catalog import ACTIVE_MODELS

TIER_ORDER = ["cp", "openai_list", "global", "us", "in_region"]
CELL_PRICE_KEYS = {"input", "output", "cache_read", "cache_write", "cache_write_1h", "long"}


@pytest.fixture()
def db(monkeypatch):
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


def test_manual_note_keeps_its_reference_right_after_the_cited_sources(db, monkeypatch):
    note = {**ds.MANUAL_NOTE, "family_key": "gpt-5.4", "prior_price": {}}
    monkeypatch.setattr(pricing_sources, "PRICE_NOTES", [note])
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    assert payload["references"][-1] == {
        "n": 9, "id": "note:gpt-5.4", "kind": "manual_note",
        "title_en": "GPT 5.4 promotion (manual note, 2026-09-23 AWS model card)",
        "title_ko": "GPT 5.4 프로모션 (수동 메모, 2026-09-23 AWS 모델 카드 기준)", "url": None, "as_of": None}
    assert [r["kind"] for r in payload["references"]][-2:] == ["price_list", "manual_note"]  # Nova (8) is last cited
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
    assert payload["references"] == []  # nothing cited, nothing listed
    assert payload["disclaimer"] == {"en": pricing_sources.DISCLAIMER["en"], "ko": pricing_sources.DISCLAIMER["ko"]}


def test_an_unknown_source_id_is_still_listed_so_its_footnote_resolves(db):
    ds.add_price(db, "openai:us-east-1:openai.gpt-5.5", 5.5, 33.0, effective_from=ds.RUN2, status="verified",
                 observed_at=ds.RUN2, source_id="mystery-source")
    db.commit()
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    (element,) = _family(payload, "gpt-5.5")["tiers"]["in_region"]
    (ref,) = [r for r in payload["references"] if r["n"] == element["footnotes"][0]]
    assert ref == {"n": 6, "id": "mystery-source", "kind": "official_page", "title_en": "mystery-source",
                   "title_ko": "mystery-source", "url": None, "as_of": "2026-09-25"}


def test_production_note_cites_the_openai_pricing_reference(db, monkeypatch):
    monkeypatch.undo()  # production PRICE_NOTES
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    assert "official_page" not in [r["kind"] for r in payload["references"]]
    sol = _family(payload, "gpt-5.6-sol")
    (note,) = sol["notes"]
    assert set(note) == {"family_key", "kind", "min_until", "prior_price", "text_ko", "text_en", "source", "source_id"}
    assert (note["source"], note["source_id"]) == ("openai_doc", "openai-pricing")
    ref = next(r for r in payload["references"] if r["id"] == "openai-pricing")
    assert (ref["n"], ref["kind"], ref["url"]) == (4, "openai_doc", "https://developers.openai.com/api/docs/pricing")


def _production_payload(notes):
    """build_pricing_payload on the real seeds of the 62 active channels plus the 9 OpenAI official prices."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    active = active_channels(ACTIVE_MODELS, [])
    assert len(active) == 71
    assert pricing_seed.ensure_seed(engine, active) == 71
    try:
        with sessionmaker(bind=engine)() as session, pytest.MonkeyPatch.context() as mp:
            mp.setattr(pricing_sources, "PRICE_NOTES", notes)
            return build_pricing_payload(session, active, now=ds.NOW)
    finally:
        engine.dispose()


def _assert_every_reference_is_cited(payload):
    refs = payload["references"]
    ref_n = {r["id"]: r["n"] for r in refs}
    cited = {n for f in payload["families"] for c in _cells(f) for n in c["footnotes"]}
    cited |= {ref_n[note["source_id"]] for f in payload["families"] for note in f["notes"]}
    assert {r["n"] for r in refs} == cited
    assert [r["n"] for r in refs] == list(range(1, len(refs) + 1))  # 1..N, no gaps, in order


def test_production_references_list_only_cited_sources():
    payload = _production_payload(pricing_sources.PRICE_NOTES)
    _assert_every_reference_is_cited(payload)
    kinds = [r["kind"] for r in payload["references"]]
    assert len(kinds) == 23
    assert {k: kinds.count(k) for k in set(kinds)} == {
        "agreement_offer": 20, "price_list": 1, "anthropic_doc": 1, "openai_doc": 1}


def test_production_manual_note_is_numbered_right_after_the_cited_sources():
    note = {**ds.MANUAL_NOTE, "family_key": "gpt-5.4", "prior_price": {}}
    payload = _production_payload([*pricing_sources.PRICE_NOTES, note])
    _assert_every_reference_is_cited(payload)
    assert [(r["n"], r["id"], r["kind"]) for r in payload["references"][-1:]] == [(24, "note:gpt-5.4", "manual_note")]


def test_production_payload_shows_the_v2_32_channels():
    payload = _production_payload(pricing_sources.PRICE_NOTES)
    order = [f["family_key"] for f in payload["families"]]
    assert order.index("claude-sonnet-5-5") + 1 == order.index("claude-sonnet-5")
    assert [f["family_key"] for f in payload["families"] if f["provider"] == "openai"][0] == "gpt-6.1-sol"
    opus5 = _family(payload, "claude-opus-5")["tiers"]
    (seoul,) = opus5["in_region"]
    assert (seoul["regions"], seoul["input"], seoul["output"], seoul["cache_read"], seoul["cache_write"],
            seoul["cache_write_1h"], seoul["long"]) == (["ap-northeast-2"], 5.5, 27.5, 0.55, 6.875, 11, None)
    assert seoul["footnotes"] == opus5["us"]["footnotes"] == opus5["global"]["footnotes"]  # one offer
    (seoul,) = _family(payload, "claude-sonnet-5")["tiers"]["in_region"]
    assert (seoul["regions"], seoul["input"], seoul["output"]) == (["ap-northeast-2"], 2.2, 11)
    s55 = _family(payload, "claude-sonnet-5-5")["tiers"]
    assert (s55["us"], s55["in_region"], s55["global"]["input"], s55["cp"]["input"]) == (None, [], 2, 2)
    g61 = _family(payload, "gpt-6.1-sol")["tiers"]
    assert [g61[t]["long"] for t in ("global", "us")] + [g61["in_region"][0]["long"]] == [None] * 3
    assert g61["openai_list"]["long"] == {"input": 4, "output": 15, "cache_read": 0.2, "cache_write": 5}
    assert payload["models"]["bedrock:ap-northeast-2:anthropic.claude-opus-5"]["input"] == 5.5


# v2.32.0 channels a v2.31.2 database does not have yet: they cite the two new offers, the Seoul in-region rows cite
# the Opus 5 and Sonnet 5 offers, CP Sonnet 5.5 cites the Anthropic doc and openai-list:gpt-6.1-sol the OpenAI doc.
V2_32_NEW_CHANNELS = {
    "global.anthropic.claude-sonnet-5-5", "anthropic:claude-sonnet-5-5",
    "bedrock:ap-northeast-2:anthropic.claude-opus-5", "bedrock:ap-northeast-2:anthropic.claude-sonnet-5",
}


def test_upgrade_seed_before_the_first_sync_dates_the_new_offers_by_their_seed_check():
    """v2.31.2 -> v2.32.0 before the first PricingSync: the two new offers are cited by seed rows only, so their
    references show their own seed check date (pricing_seed.SEED_SOURCE_DATES, 2026-09-30), not the 2026-09-27
    default that predates them. Every other source keeps the date its last sync observed it."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    active = active_channels(ACTIVE_MODELS, [])
    old = {m: i for m, i in active.items() if m not in V2_32_NEW_CHANNELS and i.family_key != "gpt-6.1-sol"}
    assert len(old) == 63
    try:
        assert pricing_seed.ensure_seed(engine, old) == 63
        synced = datetime(2026, 9, 29, 3, 0, tzinfo=timezone.utc)  # the last v2.31.2 sync
        with Session() as s:
            s.add(models.PriceSyncRun(started_at=synced, finished_at=synced + timedelta(seconds=31), status="completed"))
            for row in s.query(models.PriceHistory):
                row.observed_at = synced
            s.commit()
        assert pricing_seed.ensure_seed(engine, active) == 8  # the upgrade: backend lifespan seeds the new rows
        with Session() as s:
            payload = build_pricing_payload(s, active, now=datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc))
    finally:
        engine.dispose()

    _assert_every_reference_is_cited(payload)
    as_of = {r["id"]: r["as_of"] for r in payload["references"]}
    assert len(as_of) == 23
    assert as_of.pop("offer:offer-5fu2rhus3byrs") == "2026-09-30"  # Claude Sonnet 5.5
    assert as_of.pop("offer:offer-wbhj4kycntgkk") == "2026-09-30"  # GPT 6.1 Sol
    assert set(as_of.values()) == {"2026-09-29"}  # incl. the offers and docs the other new rows cite
    s55 = _family(payload, "claude-sonnet-5-5")["tiers"]
    assert (s55["global"]["verification"], s55["global"]["observed_at"]) == ("seed_only", None)
