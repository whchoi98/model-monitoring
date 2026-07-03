"""Unit tests for reliability channel classification — esp. OpenAI inclusion.

Regression guard for the silent-exclusion bug where OpenAI labels fell through
to channel "Other" and were dropped from the multi-channel response.
"""
from routers import reliability as rel


def test_parse_label_bedrock_and_anthropic():
    assert rel._parse_label("Bedrock Claude Sonnet 4.6 (Global)") == ("Claude Sonnet 4.6", "Bedrock Global")
    assert rel._parse_label("Bedrock Claude Sonnet 4.6 (US)") == ("Claude Sonnet 4.6", "Bedrock US")
    assert rel._parse_label("Anthropic Claude Sonnet 4.6 (US)") == ("Claude Sonnet 4.6", "Anthropic (CP on AWS)")
    assert rel._parse_label("Bedrock Nova 2.0 Lite (US)") == ("Nova 2.0 Lite", "Bedrock US")


def test_parse_label_openai_mantle_and_1p():
    assert rel._parse_label("OpenAI GPT 5.4 (us-east-1)") == ("GPT 5.4", "OpenAI us-east-1")
    assert rel._parse_label("OpenAI GPT 5.4 (us-east-2)") == ("GPT 5.4", "OpenAI us-east-2")
    assert rel._parse_label("OpenAI GPT 5.4 (us-west-2)") == ("GPT 5.4", "OpenAI us-west-2")
    assert rel._parse_label("OpenAI GPT 5.5 (1P)") == ("GPT 5.5", "OpenAI 1P")


def test_channel_sort_key_orders_openai_after_bedrock():
    chans = ["OpenAI 1P", "Bedrock US", "Anthropic (CP on AWS)", "Bedrock Global", "OpenAI us-east-1"]
    assert sorted(chans, key=rel._channel_sort_key) == [
        "Anthropic (CP on AWS)",
        "Bedrock Global",
        "Bedrock US",
        "OpenAI 1P",
        "OpenAI us-east-1",
    ]


def test_unmatched_label_is_other():
    assert rel._parse_label("weird-label")[1] == "Other"
