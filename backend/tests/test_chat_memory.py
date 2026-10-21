"""AgentCore request validation and history payloads, without a provider call."""

from datetime import datetime, timezone

import boto3
from botocore.stub import ANY, Stubber

from agent import memory


def test_memory_writes_a_timestamp_and_reads_conversation_payloads(monkeypatch):
    sdk = boto3.client("bedrock-agentcore", region_name="ap-northeast-2",
                       aws_access_key_id="fake", aws_secret_access_key="fake")
    monkeypatch.setattr(memory, "_client", lambda: sdk)
    monkeypatch.setenv("AGENTCORE_MEMORY_ID", "monitor_memory-1234567890")
    common = {"memoryId": "monitor_memory-1234567890", "actorId": "guest-example", "sessionId": "chat-example"}
    event = {**common, "eventId": "event-1234567890", "eventTimestamp": datetime(2026, 10, 21, tzinfo=timezone.utc),
             "payload": [{"conversational": {"role": "USER", "content": {"text": "Remember this question"}}}]}
    with Stubber(sdk) as stub:
        stub.add_response("create_event", {"event": event}, {**common, "eventTimestamp": ANY, "payload": event["payload"]})
        stub.add_response("list_events", {"events": [event]}, {**common, "includePayloads": True, "maxResults": 20})
        assert memory.append_message("guest-example", "chat-example", "USER", "Remember this question") == "event-1234567890"
        rows = memory.list_recent_messages("guest-example", "chat-example")
        assert [(row["role"], row["content"]) for row in rows] == [("USER", "Remember this question")]
        stub.assert_no_pending_responses()
