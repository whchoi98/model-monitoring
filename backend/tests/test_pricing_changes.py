"""pricing_changes — run-to-run unit price changes from the run snapshots (v2.40.0, ADR-035). Pure, no DB."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from pricing_changes import changes_block, compare_snapshots, select_runs
from pricing_parsers import PRICE_FIELDS

T = datetime(2026, 11, 5, 3, 0, tzinfo=timezone.utc)
SONNET_G = "global.anthropic.claude-sonnet-5-5"
SONNET_CP = "anthropic:claude-sonnet-5-5"
SOL_US = "openai:us:us.openai.gpt-6-sol"
NOVA = "us.amazon.nova-2-lite-v1:0"
TERRA_E1 = "openai:us-east-1:openai.gpt-5.6-terra"


def _shown(i, o, **extra):
    return {**dict.fromkeys(PRICE_FIELDS), "input": i, "output": o, **extra}


def _ch(family_key, family, provider, tier, shown, pending=None, result="unchanged", region=None):
    return {"family_key": family_key, "family": family, "provider": provider, "tier": tier, "region": region,
            "shown": shown, "pending": pending, "result": result}



BASE = {
    SONNET_G: _ch("claude-sonnet-5-5", "Claude Sonnet 5.5", "anthropic", "global", _shown(2, 10, cache_read=0.2)),
    SONNET_CP: _ch("claude-sonnet-5-5", "Claude Sonnet 5.5", "anthropic", "cp", _shown(2, 10, cache_read=0.2)),
    SOL_US: _ch("gpt-6-sol", "GPT 6 Sol", "openai", "us", _shown(2.2, 11)),
    NOVA: _ch("nova-2-lite", "Nova 2.0 Lite", "amazon", "us", _shown(0.33, 2.75)),
}


def _with(**changes):
    out = {mid: dict(ch) for mid, ch in BASE.items()}
    for mid, ch in changes.items():
        out[mid] = ch
    return {"version": 1, "channels": out}


def test_identical_snapshots_have_no_change():
    assert compare_snapshots(_with(), _with()) == []


def test_a_shown_field_change_is_a_price_item():
    after = _with(**{SONNET_G: {**BASE[SONNET_G], "shown": _shown(2, 10, cache_read=0.1)}})
    assert compare_snapshots(_with(), after) == [{
        "model_id": SONNET_G, "family_key": "claude-sonnet-5-5", "family": "Claude Sonnet 5.5", "provider": "anthropic",
        "tier": "global", "region": None, "kind": "price", "field": "cache_read", "before": 0.2, "after": 0.1}]


def test_a_first_time_value_has_a_null_before():
    after = _with(**{NOVA: {**BASE[NOVA], "shown": _shown(0.33, 2.75, cache_read=0.0825)}})
    (item,) = compare_snapshots(_with(), after)
    assert (item["kind"], item["field"], item["before"], item["after"]) == ("price", "cache_read", None, 0.0825)


def test_a_pending_value_starts_and_clears():
    started = _with(**{SOL_US: {**BASE[SOL_US], "pending": {"input": 3.3}, "result": "pending"}})
    (item,) = compare_snapshots(_with(), started)
    assert (item["kind"], item["field"], item["before"], item["after"]) == ("pending", "input", None, 3.3)
    approved = _with(**{SOL_US: {**BASE[SOL_US], "shown": _shown(3.3, 11)}})
    assert [(i["kind"], i["field"], i["before"], i["after"]) for i in compare_snapshots(started, approved)] == [
        ("price", "input", 2.2, 3.3), ("pending", "input", 3.3, None)]


def test_a_skipped_check_and_its_recovery():
    failed = _with(**{SONNET_CP: {**BASE[SONNET_CP], "result": "skipped:parse_failed"}})
    (item,) = compare_snapshots(_with(), failed)
    assert (item["kind"], item["before"], item["after"]) == ("check", "ok", "skipped:parse_failed")
    (back,) = compare_snapshots(failed, _with())
    assert (back["kind"], back["before"], back["after"]) == ("check", "skipped:parse_failed", "ok")


def test_changed_enriched_and_pending_results_are_all_ok_checks():
    for result in ("changed", "enriched", "pending", "no_baseline", "rejected"):
        assert compare_snapshots(_with(), _with(**{NOVA: {**BASE[NOVA], "result": result}})) == []


def test_a_new_and_a_left_channel_give_one_channel_item_each():
    after = _with()
    del after["channels"][NOVA]
    after["channels"][TERRA_E1] = _ch("gpt-5.6-terra", "GPT 5.6 Terra", "openai", "in_region", _shown(2.2, 13.2),
                                      region="us-east-1")
    items = compare_snapshots(_with(), after)
    assert [(i["model_id"], i["kind"], i["field"], i["before"], i["after"], i["region"]) for i in items] == [
        (TERRA_E1, "channel", None, None, "present", "us-east-1"),
        (NOVA, "channel", None, "present", None, None),
    ]


def test_items_follow_provider_family_tier_kind_and_field_order():
    after = _with(**{
        NOVA: {**BASE[NOVA], "shown": _shown(0.4, 2.75)},
        SOL_US: {**BASE[SOL_US], "shown": _shown(2.2, 12), "pending": {"input": 3.3}},
        SONNET_G: {**BASE[SONNET_G], "shown": _shown(2, 11, cache_read=0.1)},
        SONNET_CP: {**BASE[SONNET_CP], "result": "skipped:not_found"},
    })
    assert [(i["model_id"], i["kind"], i["field"]) for i in compare_snapshots(_with(), after)] == [
        (SONNET_CP, "check", None),               # anthropic, Sonnet 5.5, cp before global
        (SONNET_G, "price", "output"), (SONNET_G, "price", "cache_read"),
        (SOL_US, "price", "output"), (SOL_US, "pending", "input"),   # openai
        (NOVA, "price", "input"),                 # amazon last
    ]


def _run(id_, status="completed", snapshot=True, minutes=0):
    summary = {"snapshot": _with()} if snapshot else {"sources": {}}
    return SimpleNamespace(id=id_, status=status, finished_at=T - timedelta(minutes=minutes), summary=summary)


def test_select_runs_skips_failed_runs_and_needs_a_snapshot_on_the_latest():
    runs = [_run(9, "failed", snapshot=False), _run(8, snapshot=False, minutes=1), _run(7, "partial", minutes=2),
            _run(6, "failed", minutes=3), _run(5, minutes=4)]
    latest, previous = select_runs(runs)
    assert (latest.id, previous.id) == (7, 5)


def test_no_comparison_until_the_previous_run_has_a_snapshot():
    assert changes_block(*select_runs([_run(3), _run(2, snapshot=False)])) == {"available": False, "run_id": 3}
    assert changes_block(*select_runs([_run(3)])) == {"available": False, "run_id": 3}
    assert changes_block(*select_runs([])) == {"available": False, "run_id": None}


def test_changes_block_names_both_runs():
    block = changes_block(*select_runs([_run(4), _run(3, minutes=720)]))
    assert block == {"available": True, "run_id": 4, "finished_at": "2026-11-05T03:00:00Z", "previous_run_id": 3,
                     "previous_finished_at": "2026-11-04T15:00:00Z", "items": []}
