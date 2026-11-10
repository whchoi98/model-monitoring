"""Families that left monitoring but stay sample data in the pricing mechanics tests (v2.43.0, ADR-038).

The sync, payload and export tests were written against the 2026-09-27 official sources (`fixtures/pricing/`) with
GPT 5.6 Sol, Terra, Luna, GPT 5.5 and Claude Opus 4.8 as sample channels, and the golden payload numbers its footnotes
in that order. v2.43.0 took those families out of `pricing_sources`, so `price_identity()` no longer classifies them.
`register(monkeypatch)` puts exactly their v2.42.0 table entries back for one test, so the goldens and the sync
expectations stay as they were. Tests of the real catalog (seeds, identity counts, `test_production_*`) do not
need it — the extra entries change nothing for the active channels, whose relative family order is the same.
"""

import pricing_changes
import pricing_payload
import pricing_sources as ps

# pricing_sources.FAMILY_ORDER of v2.42.0 (18 families) — v2.43.0 removed Claude Opus 4.8 and the four GPT 5.x families
V242_FAMILY_ORDER: tuple[str, ...] = (
    "Claude Fable 5.2", "Claude Fable 5.1", "Claude Opus 5.5", "Claude Opus 5", "Claude Opus 4.8",
    "Claude Sonnet 5.5", "Claude Sonnet 5", "Claude Haiku 5.5", "Nova 2.0 Lite", "GPT 6.1 Sol", "GPT 6.1 Terra",
    "GPT 6 Astra", "GPT 6 Sol", "GPT 6 Luna", "GPT 5.6 Sol", "GPT 5.6 Terra", "GPT 5.6 Luna", "GPT 5.5",
)
_CLAUDE_FM = {"anthropic.claude-opus-4-8": ("claude-opus-4-8", "Claude Opus 4.8")}
_OPENAI_FM = {
    "openai.gpt-5.6-sol": ("gpt-5.6-sol", "GPT 5.6 Sol"), "openai.gpt-5.6-terra": ("gpt-5.6-terra", "GPT 5.6 Terra"),
    "openai.gpt-5.6-luna": ("gpt-5.6-luna", "GPT 5.6 Luna"), "openai.gpt-5.5": ("gpt-5.5", "GPT 5.5"),
}


def register(monkeypatch) -> None:
    """Classify the v2.43.0 retired families again for the duration of one test (monkeypatch undoes it)."""
    for fm, (family_key, family) in _CLAUDE_FM.items():
        monkeypatch.setitem(ps._BEDROCK_CLAUDE_FM, fm, (family_key, family))
        monkeypatch.setitem(ps._CLAUDE_FAMILY_NAMES, family_key, family)
        monkeypatch.setitem(ps.ANTHROPIC_DOC_NAMES, family_key, family)
    at = ps._CP_TARGETS.index("opus-5") + 1  # v2.42.0 order: … opus-5, opus-4-8, sonnet-5-5 …
    monkeypatch.setattr(ps, "_CP_TARGETS", (*ps._CP_TARGETS[:at], "opus-4-8", *ps._CP_TARGETS[at:]))
    for fm, (family_key, family) in _OPENAI_FM.items():
        monkeypatch.setitem(ps._OPENAI_FM, fm, (family_key, family))
        monkeypatch.setitem(ps._OPENAI_LIST_FAMILIES, family_key, family)
    for module in (ps, pricing_payload, pricing_changes):  # the last two bound FAMILY_ORDER at import
        monkeypatch.setattr(module, "FAMILY_ORDER", V242_FAMILY_ORDER)
