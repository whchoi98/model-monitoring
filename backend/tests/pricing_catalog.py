"""pricing 테스트 공용 데이터 — 운영 /api/models(2026-09-26) 활성 55채널 (v2.30.0). 수집 대상 아님."""

_CLAUDE = [  # (FM id, family_key, family) — Global, US가 같은 FM id
    ("anthropic.claude-fable-5-1", "claude-fable-5-1", "Claude Fable 5.1"),
    ("anthropic.claude-fable-5", "claude-fable-5", "Claude Fable 5"),
    ("anthropic.claude-opus-5-5", "claude-opus-5-5", "Claude Opus 5.5"),
    ("anthropic.claude-opus-5", "claude-opus-5", "Claude Opus 5"),
    ("anthropic.claude-opus-4-8", "claude-opus-4-8", "Claude Opus 4.8"),
    ("anthropic.claude-opus-4-7", "claude-opus-4-7", "Claude Opus 4.7"),
    ("anthropic.claude-opus-4-6-v1", "claude-opus-4-6", "Claude Opus 4.6"),
    ("anthropic.claude-sonnet-5", "claude-sonnet-5", "Claude Sonnet 5"),
    ("anthropic.claude-sonnet-4-6", "claude-sonnet-4-6", "Claude Sonnet 4.6"),
    ("anthropic.claude-haiku-4-5-20251001-v1:0", "claude-haiku-4-5", "Claude Haiku 4.5"),
]
# CP 디스커버리 id (Opus 4.6은 CP 채널 없음, Haiku는 날짜 접미사)
_CP_IDS = {
    "claude-fable-5-1": "claude-fable-5-1", "claude-fable-5": "claude-fable-5",
    "claude-opus-5-5": "claude-opus-5-5", "claude-opus-5": "claude-opus-5",
    "claude-opus-4-8": "claude-opus-4-8", "claude-opus-4-7": "claude-opus-4-7",
    "claude-sonnet-5": "claude-sonnet-5", "claude-sonnet-4-6": "claude-sonnet-4-6",
    "claude-haiku-4-5": "claude-haiku-4-5-20251001",
}
_OPENAI = [  # (FM id, family_key, family, channels) — prober _OPENAI_MODEL_SPECS와 같은 리전
    ("openai.gpt-6-astra", "gpt-6-astra", "GPT 6 Astra", ("global", "us", "us-west-2")),
    ("openai.gpt-6-sol", "gpt-6-sol", "GPT 6 Sol", ("global", "us", "us-east-1")),
    ("openai.gpt-6-luna", "gpt-6-luna", "GPT 6 Luna", ("global", "us", "us-east-1")),
    ("openai.gpt-5.6-sol", "gpt-5.6-sol", "GPT 5.6 Sol", ("global", "us-east-1", "us-east-2")),
    ("openai.gpt-5.6-terra", "gpt-5.6-terra", "GPT 5.6 Terra", ("global", "us-east-1", "us-east-2", "us-west-2")),
    ("openai.gpt-5.6-luna", "gpt-5.6-luna", "GPT 5.6 Luna", ("global", "us-east-1", "us-east-2", "us-west-2")),
    ("openai.gpt-5.5", "gpt-5.5", "GPT 5.5", ("us-east-1", "us-east-2")),
    ("openai.gpt-5.4", "gpt-5.4", "GPT 5.4", ("us-east-1", "us-east-2", "us-west-2")),
]


def _openai_id(fm: str, region: str) -> str:
    return f"openai:{region}:{region}.{fm}" if region in ("global", "us") else f"openai:{region}:{fm}"


def _channel(region: str) -> str:
    return region if region in ("global", "us") else f"inregion:{region}"


# model_id → (family_key, family, provider, channel, source_kind, source_ref)
EXPECTED_IDENTITY: dict[str, tuple[str, str, str, str, str, str]] = {
    **{f"{p}.{fm}": (fk, fam, "anthropic", p, "offer", fm) for p in ("global", "us") for fm, fk, fam in _CLAUDE},
    "us.amazon.nova-2-lite-v1:0": ("nova-2-lite", "Nova 2.0 Lite", "amazon", "us", "pricelist", "nova-2-lite"),
    **{f"anthropic:{_CP_IDS[fk]}": (fk, fam, "anthropic", "cp", "anthropic_doc", fam) for _, fk, fam in _CLAUDE if fk in _CP_IDS},
    **{_openai_id(fm, r): (fk, fam, "openai", _channel(r), "offer", fm) for fm, fk, fam, rs in _OPENAI for r in rs},
}


def _label(identity: tuple) -> str:
    _, family, provider, channel, _, _ = identity
    if channel == "cp":
        return f"Anthropic {family} (US)"
    suffix = {"global": "Global", "us": "US"}.get(channel) or channel.split(":", 1)[1]
    return f"{'OpenAI' if provider == 'openai' else 'Bedrock'} {family} ({suffix})"


ACTIVE_MODELS: dict[str, str] = {mid: _label(i) for mid, i in EXPECTED_IDENTITY.items()}  # prober 라벨 규약

HIDDEN_1P_MODELS: dict[str, str] = {  # 휴면 1P — 기본 숨김 패턴 "(1P)"
    f"openai:1p:{fk}": f"OpenAI {fam} (1P)"
    for fk, fam in (("gpt-5.6-sol", "GPT 5.6 Sol"), ("gpt-5.6-terra", "GPT 5.6 Terra"),
                    ("gpt-5.6-luna", "GPT 5.6 Luna"), ("gpt-5.4", "GPT 5.4"), ("gpt-5.5", "GPT 5.5"))
}

# 2026-09-23 CP /v1/models 실측 순서 — 점 버전이 base보다 먼저 온다
CP_MODEL_IDS_20260923 = [
    "claude-opus-5-5", "claude-fable-5-1", "claude-opus-5", "claude-sonnet-5", "claude-fable-5",
    "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-6", "claude-opus-4-6",
    "claude-opus-4-5-20251101", "claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929",
]
