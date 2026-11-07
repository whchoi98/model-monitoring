"""model_explorer.examples — the code examples moved from the frontend without a byte changing (v2.40.0, ADR-035).

fixtures/explorer_examples_v2390.json is what frontend/src/lib/modelExplorer.ts codeExamples() returned at c96a592
(v2.39.0) for one model id per channel type, KO and EN, dumped by node importing the .ts file. Regenerate it only for an
intended example change, and then change examples.py in the same commit.
"""

import hashlib
import json
from pathlib import Path

import pytest

from model_explorer.examples import API_IDS, API_NAMES, code_examples
from model_explorer.execute import PLACEHOLDERS
from tests.pricing_catalog import ACTIVE_MODELS

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "explorer_examples_v2390.json").read_text(encoding="utf-8"))
GOLDEN_IDS = list(GOLDEN["examples"])


def _without_comments(code: str) -> list[str]:
    return [line for line in code.split("\n") if not line.lstrip().startswith("#")]


@pytest.mark.parametrize("model_id", GOLDEN_IDS)
@pytest.mark.parametrize("lang", ["ko", "en"])
def test_examples_equal_the_v2390_frontend_output_byte_for_byte(model_id, lang):
    want = GOLDEN["examples"][model_id][lang]
    got = code_examples(model_id)
    assert [(e["label"], e["api"], e["language"], e["description"][lang], e["code"][lang]) for e in got] == [
        (e["label"], e["api"], e["language"], e["description"], e["code"]) for e in want]


def test_the_golden_covers_every_channel_type():
    assert GOLDEN_IDS == [
        "global.anthropic.claude-opus-5", "us.anthropic.claude-haiku-5-5", "us.amazon.nova-2-lite-v1:0",
        "bedrock:ap-northeast-2:anthropic.claude-opus-5", "anthropic:claude-sonnet-5-5",
        "openai:us-east-1:openai.gpt-6-sol", "openai:global:global.openai.gpt-6.1-sol",
        "openai:us:us.openai.gpt-6-astra", "openai:1p:gpt-5.5",
    ]


@pytest.mark.parametrize("model_id", [*ACTIVE_MODELS, "openai:1p:gpt-5.5"])
def test_ko_and_en_differ_only_in_comment_lines(model_id):
    for example in code_examples(model_id):
        assert _without_comments(example["code"]["ko"]) == _without_comments(example["code"]["en"])


@pytest.mark.parametrize("model_id, api_ids", [
    ("global.anthropic.claude-opus-5", ["converse", "invoke_model", "messages"]),
    ("us.anthropic.claude-haiku-5-5", ["converse", "invoke_model", "messages"]),
    ("bedrock:ap-northeast-2:anthropic.claude-sonnet-5", ["converse", "invoke_model", "messages"]),
    ("us.amazon.nova-2-lite-v1:0", ["converse"]),
    ("anthropic:claude-opus-5-5", ["messages"]),
    ("openai:us-east-1:openai.gpt-6.1-terra", ["responses"]),
    ("openai:global:global.openai.gpt-6-luna", ["responses"]),
    ("openai:us:us.openai.gpt-6-sol", ["responses"]),
    ("openai:1p:gpt-5.6-sol", ["responses"]),
])
def test_api_ids_per_channel_type(model_id, api_ids):
    examples = code_examples(model_id)
    assert [e["api_id"] for e in examples] == api_ids
    assert all(e["api"] == API_NAMES[e["api_id"]] and e["api_id"] in API_IDS for e in examples)


def test_every_active_model_has_an_example_and_85_in_all():
    counts = {model_id: len(code_examples(model_id)) for model_id in ACTIVE_MODELS}
    assert min(counts.values()) >= 1
    assert sum(counts.values()) == 85


def test_every_placeholder_in_every_example_is_in_the_substitution_table():
    import re

    for model_id in [*ACTIVE_MODELS, "openai:1p:gpt-5.5"]:
        for example in code_examples(model_id):
            for lang in ("ko", "en"):
                assert set(re.findall(r'"<[^"\n]*>"', example["code"][lang])) <= set(PLACEHOLDERS), (model_id, lang)


def test_code_sha_is_the_sha256_of_the_en_code():
    for model_id in GOLDEN_IDS:
        for example in code_examples(model_id):
            assert example["code_sha"] == hashlib.sha256(example["code"]["en"].encode("utf-8")).hexdigest()


def test_the_in_region_key_calls_its_own_region_with_the_bare_fm_id():
    converse = code_examples("bedrock:ap-northeast-2:anthropic.claude-opus-5")[0]["code"]["en"]
    assert 'region_name="ap-northeast-2"' in converse and 'modelId="anthropic.claude-opus-5"' in converse
    assert "bedrock:" not in converse


def test_us_profiles_call_us_east_1_and_global_profiles_seoul():
    assert 'region_name="us-east-1"' in code_examples("us.anthropic.claude-opus-5")[0]["code"]["en"]
    assert 'region_name="ap-northeast-2"' in code_examples("global.anthropic.claude-opus-5")[0]["code"]["en"]
