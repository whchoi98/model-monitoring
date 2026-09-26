"""pricing_payload.build_pricing_payload — exact /api/pricing JSON on a small golden dataset (v2.30.0).

Dataset (tests/_pricing_dataset.py): Claude Opus 5.5 on three channels, a stale Nova row, GPT 6 Luna with no
price rows, GPT 5.6 Sol with two pending rows on its Global channel and a seed-only in-region row, GPT 5.6 Terra
whose us-west-2 price differs from us-east-1/us-east-2, GPT 5.5 seed-only, GPT 5.4 on three equal regions, and
rows for inactive model_ids that must never appear. OFFICIAL_PAGES and PRICE_NOTES are pinned to test copies so the golden does
not depend on their production wording; DISCLAIMER is the spec text.
"""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import pricing_sources
from pricing_payload import build_pricing_payload, price_number, price_text
from tests import _pricing_dataset as ds
from tests._pricing_dataset import EXPECTED_PAYLOAD, OPUS, SOL


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


def test_payload_matches_the_golden_exactly(db):
    assert build_pricing_payload(db, ds.active(), now=ds.NOW) == EXPECTED_PAYLOAD


def test_every_footnote_resolves_to_the_cited_source(db):
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    refs = {r["n"]: r["id"] for r in payload["references"]}
    assert sorted(refs) == list(range(1, len(refs) + 1))
    for family in payload["families"]:
        cells = [c for c in (family["tiers"][t] for t in ("cp", "global", "us")) if c] + family["tiers"]["in_region"]
        for cell in cells:
            assert [refs[n] for n in cell["footnotes"]] == cell["source_ids"]


def test_numbers_serialize_without_trailing_zeros():
    assert price_number(4.0) == 4 and isinstance(price_number(4.0), int)
    assert price_number(4.40) == 4.4
    assert price_number(4.0 * 1.1) == 4.4  # 4.4000000000000004
    assert price_number(0.1234567) == 0.123457
    assert price_text(4.4) == "4.4"
    assert price_text(0.11) == "0.11"
    assert price_text(20.0) == "20"
    assert price_text(0.00001) == "0.00001"


def test_promo_note_drops_once_the_prior_price_is_observed(db):
    ds.add_price(db, "openai:us-east-1:openai.gpt-5.6-sol", 5.5, 33.0, effective_from=ds.RUN2, status="verified",
                 observed_at=ds.RUN2, source_id=SOL)
    db.commit()
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    sol = next(f for f in payload["families"] if f["family_key"] == "gpt-5.6-sol")
    assert sol["notes"] == []
    assert [r["kind"] for r in payload["references"]].count("manual_note") == 0


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
    cited = kinds.count("agreement_offer") + kinds.count("price_list") + kinds.count("anthropic_doc")
    assert kinds[cited:] == ["official_page"] * 9 + ["manual_note"]
    assert {r["url"] for r in payload["references"] if r["kind"] == "official_page"} == {
        "https://aws.amazon.com/bedrock/pricing/",
        *(f"https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-{slug}.html" for slug in (
            "gpt-54", "gpt-55", "gpt-56-sol", "gpt-56-terra", "gpt-56-luna", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna")),
    }
    note = next(r for r in payload["references"] if r["kind"] == "manual_note")
    assert note["id"] == "note:gpt-5.6-sol" and note["url"] is None
