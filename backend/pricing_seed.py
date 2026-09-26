"""단가 seed — 활성 55채널 공식 단가 초기값과 model_id 단위 멱등 삽입 (v2.30.0, ADR-030).

출처(2026-09-26 스파이크, USD per 1M tokens, Standard 입력/출력): Bedrock agreement offer rate card(FM 18개,
offerId 리전 무관), AWS Price List(Nova 2.0 Lite USE1, 1K tokens × 1000), Anthropic pricing.md(CP 9).
v2.29.1 대비 교정 11채널(결정 8, 과거까지): Bedrock Claude US 10 = Global × 1.1, Nova 2.0 Lite 0.33 / 2.75.
나머지 44채널은 v2.29.1 값과 같다. 새 모델은 pricing_sources.py 매핑과 함께 여기 표를 고친다.
"""

import logging
from datetime import date, datetime, timezone
from typing import Mapping

from sqlalchemy import insert, select, text

from models import PriceHistory
from pricing_sources import (
    ANTHROPIC_SOURCE_ID, EPOCH, NOVA_USAGETYPES, PriceIdentity, offer_source_id, pricelist_source_id,
)

logger = logging.getLogger(__name__)

SEED_SOURCE_DATE = date(2026, 9, 26)  # seed만 있는 참고 자료의 확인일(as_of)
# backend 태스크 기동과 PricingSync 러너가 겹쳐도 같은 model_id를 두 번 seed하지 않는다(트랜잭션 잠금).
# 잠금 전에 트랜잭션 한정 상한을 건다 — 잠금 대기나 느린 쿼리가 lifespan/러너를 붙잡지 않게.
_SEED_TIMEOUT_SQL = ("SET LOCAL statement_timeout = '30000'", "SET LOCAL lock_timeout = '5000'")
_SEED_LOCK_SQL = "SELECT pg_advisory_xact_lock(917350003)"

# Bedrock Claude FM id → (offerId, Global in, Global out, US in, US out). US = USE1_*, Global = APN2_*_global.
_CLAUDE: dict[str, tuple[str, float, float, float, float]] = {
    "anthropic.claude-fable-5-1": ("offer-icq4574v6gz3i", 10.0, 50.0, 11.0, 55.0),
    "anthropic.claude-fable-5": ("offer-vk3fuman5qwzy", 10.0, 50.0, 11.0, 55.0),
    "anthropic.claude-opus-5-5": ("offer-7sp77cpl4rveu", 4.0, 20.0, 4.4, 22.0),
    "anthropic.claude-opus-5": ("offer-f3u6lgbrem3zs", 5.0, 25.0, 5.5, 27.5),
    "anthropic.claude-opus-4-8": ("offer-wdkl4yk6s7uu4", 5.0, 25.0, 5.5, 27.5),
    "anthropic.claude-opus-4-7": ("offer-sltne4evyuyeu", 5.0, 25.0, 5.5, 27.5),
    "anthropic.claude-opus-4-6-v1": ("offer-ee7a27hh4hr62", 5.0, 25.0, 5.5, 27.5),
    "anthropic.claude-sonnet-5": ("offer-2ykemehpsyf7g", 2.0, 10.0, 2.2, 11.0),
    "anthropic.claude-sonnet-4-6": ("offer-ldnd26nhxx676", 3.0, 15.0, 3.3, 16.5),
    "anthropic.claude-haiku-4-5-20251001-v1:0": ("offer-fudwqbphlos64", 1.0, 5.0, 1.1, 5.5),
}
# OpenAI FM id → (offerId, US CRIS와 in-region in, out, Global in, out, 채널 리전)
_OPENAI: dict[str, tuple[str, float, float, float | None, float | None, tuple[str, ...]]] = {
    "openai.gpt-6-astra": ("offer-7epta7rbw5aws", 11.0, 55.0, 10.0, 50.0, ("global", "us", "us-west-2")),
    "openai.gpt-6-sol": ("offer-pycji3sz5gpcc", 2.2, 11.0, 2.0, 10.0, ("global", "us", "us-east-1")),
    "openai.gpt-6-luna": ("offer-gmo53nkzc5or6", 0.11, 0.55, 0.1, 0.5, ("global", "us", "us-east-1")),
    "openai.gpt-5.6-sol": ("offer-gnqokrqqvdbgw", 4.4, 22.0, 4.0, 20.0, ("global", "us-east-1", "us-east-2")),
    "openai.gpt-5.6-terra": ("offer-3dvyrx3okd4lq", 2.2, 13.2, 2.0, 12.0, ("global", "us-east-1", "us-east-2", "us-west-2")),
    "openai.gpt-5.6-luna": ("offer-bklbyf2ewuawu", 0.22, 1.32, 0.2, 1.2, ("global", "us-east-1", "us-east-2", "us-west-2")),
    "openai.gpt-5.5": ("offer-rtwlbb46hcxpw", 5.5, 33.0, None, None, ("us-east-1", "us-east-2")),
    "openai.gpt-5.4": ("offer-5l5a5izq5fbec", 2.75, 16.5, None, None, ("us-east-1", "us-east-2", "us-west-2")),
}


def _openai_seed(fm: str, region: str, spec: tuple) -> tuple[str, tuple[float, float, str]]:
    offer, r_in, r_out, g_in, g_out, _ = spec
    src = offer_source_id(offer)
    if region == "global":
        return f"openai:global:global.{fm}", (g_in, g_out, src)
    mid = f"openai:us:us.{fm}" if region == "us" else f"openai:{region}:{fm}"
    return mid, (r_in, r_out, src)


# model_id → (input, output, source_id) — CP를 뺀 활성 46채널
SEED: dict[str, tuple[float, float, str]] = {
    **{f"global.{fm}": (g_in, g_out, offer_source_id(o)) for fm, (o, g_in, g_out, _, _) in _CLAUDE.items()},
    **{f"us.{fm}": (u_in, u_out, offer_source_id(o)) for fm, (o, _, _, u_in, u_out) in _CLAUDE.items()},
    "us.amazon.nova-2-lite-v1:0": (0.33, 2.75, pricelist_source_id(NOVA_USAGETYPES["nova-2-lite"][0])),
    **dict(_openai_seed(fm, r, spec) for fm, spec in _OPENAI.items() for r in spec[5]),
}

# Claude Platform on AWS — model_id가 디스커버리로 정해지므로(날짜 접미사) family_key 단위
CP_SEED: dict[str, tuple[float, float, str]] = {
    fk: (i, o, ANTHROPIC_SOURCE_ID)
    for fk, i, o in (
        ("claude-fable-5-1", 10.0, 50.0), ("claude-fable-5", 10.0, 50.0), ("claude-opus-5-5", 4.0, 20.0),
        ("claude-opus-5", 5.0, 25.0), ("claude-opus-4-8", 5.0, 25.0), ("claude-opus-4-7", 5.0, 25.0),
        ("claude-sonnet-5", 2.0, 10.0), ("claude-sonnet-4-6", 3.0, 15.0), ("claude-haiku-4-5", 1.0, 5.0),
    )
}


def seed_rows(active: Mapping[str, PriceIdentity]) -> dict[str, tuple[float, float, str]]:
    """활성 채널 → {model_id: seed}. CP는 family_key로 풀고, seed 없는 id는 경고 후 뺀다(동기화가 no_baseline)."""
    out: dict[str, tuple[float, float, str]] = {}
    for model_id, ident in active.items():
        seed = CP_SEED.get(ident.family_key) if ident.channel == "cp" else SEED.get(model_id)
        if seed is None:
            logger.warning("No seed price for %s (%s, %s)", model_id, ident.family_key, ident.channel)
            continue
        out[model_id] = seed
    return out


def ensure_seed(engine, active: Mapping[str, PriceIdentity]) -> int:
    """price_history에 행이 하나도 없는 활성 model_id에만 seed 행을 넣고 넣은 수를 돌려준다.

    model_id 단위 멱등(테이블 전체 비었는지 보지 않음), 자체 트랜잭션, PostgreSQL은 SET LOCAL
    statement_timeout 30초와 lock_timeout 5초를 건 뒤 pg_advisory_xact_lock(917350003) 아래(SQLite 생략).
    effective_from=EPOCH, status='seed', observed_at=NULL. 예외는 호출부(main.py lifespan, pricing_sync_runner)로 올린다.
    """
    rows = seed_rows(active)
    if not rows:
        return 0
    table = PriceHistory.__table__
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            for sql in _SEED_TIMEOUT_SQL:
                conn.execute(text(sql))
            conn.execute(text(_SEED_LOCK_SQL))
        existing = set(conn.execute(
            select(table.c.model_id).where(table.c.model_id.in_(list(rows))).distinct()
        ).scalars())
        created_at = datetime.now(timezone.utc)
        values = [
            {"model_id": mid, "family_key": active[mid].family_key, "channel": active[mid].channel,
             "input_per_mtok": float(i), "output_per_mtok": float(o), "effective_from": EPOCH,
             "source_id": src, "status": "seed", "observed_at": None, "run_id": None, "created_at": created_at}
            for mid, (i, o, src) in rows.items() if mid not in existing
        ]
        if values:
            conn.execute(insert(table), values)
    if values:
        logger.info("Price seed inserted %d rows (%d already had price history)", len(values), len(existing))
    return len(values)
