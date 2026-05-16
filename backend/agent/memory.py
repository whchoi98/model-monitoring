"""AgentCore Memory wrapper.

대화 컨텍스트를 AWS Bedrock AgentCore Memory에 영속화한다.
환경변수 `AGENTCORE_MEMORY_ID`로 memory ID를 받는다 (CDK가 SSM 통해 주입).

세션 ID는 사용자 단위 + 대화 단위로 부여: `chat-{username}-{conversation_uuid}`.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_MEMORY_ID_ENV = "AGENTCORE_MEMORY_ID"
_AWS_REGION_ENV = "AWS_REGION"


def _get_memory_id() -> Optional[str]:
    """환경변수에서 memory ID 조회 (미설정 시 None — 호출자가 graceful degrade)."""
    return os.environ.get(_MEMORY_ID_ENV)


def _client():
    region = os.environ.get(_AWS_REGION_ENV, "us-east-1")
    return boto3.client("bedrock-agentcore", region_name=region)


def append_message(
    actor_id: str,
    session_id: str,
    role: str,
    content: str,
) -> Optional[str]:
    """user/assistant 메시지를 AgentCore Memory에 이벤트로 기록.

    반환: 생성된 event ID. 실패 시 None (chatbot 흐름을 깨지 않기 위해).
    """
    memory_id = _get_memory_id()
    if not memory_id:
        logger.warning("AGENTCORE_MEMORY_ID 미설정 — Memory 기록 skip")
        return None

    try:
        # AgentCore CreateEvent API — payload는 conversational 형태.
        resp = _client().create_event(
            memoryId=memory_id,
            actorId=actor_id,
            sessionId=session_id,
            payload=[
                {
                    "conversational": {
                        "role": role,  # 'USER' | 'ASSISTANT'
                        "content": {"text": content},
                    }
                }
            ],
        )
        return resp.get("event", {}).get("eventId")
    except ClientError:
        logger.exception("AgentCore Memory create_event 실패")
        return None
    except Exception:  # noqa: BLE001 — chat 흐름 보호
        logger.exception("AgentCore Memory 호출 예기치 못한 실패")
        return None


def list_recent_messages(
    actor_id: str,
    session_id: str,
    limit: int = 20,
) -> List[dict]:
    """세션의 최근 메시지 N건 회수.

    반환 형태: [{role, content, timestamp_iso}, ...] (오래된 → 최신).
    """
    memory_id = _get_memory_id()
    if not memory_id:
        return []

    try:
        resp = _client().list_events(
            memoryId=memory_id,
            actorId=actor_id,
            sessionId=session_id,
            maxResults=limit,
        )
        events = resp.get("events", [])
        # API는 최신순일 수 있으므로 오래된 → 최신 정렬.
        events.sort(key=lambda e: e.get("eventTimestamp", 0))
        messages: List[dict] = []
        for ev in events:
            for item in ev.get("payload", []):
                conv = item.get("conversational")
                if not conv:
                    continue
                messages.append(
                    {
                        "role": conv.get("role", "USER"),
                        "content": conv.get("content", {}).get("text", ""),
                        "timestamp_iso": ev.get("eventTimestamp"),
                    }
                )
        return messages
    except ClientError:
        logger.exception("AgentCore Memory list_events 실패")
        return []
    except Exception:  # noqa: BLE001
        logger.exception("AgentCore Memory list 예기치 못한 실패")
        return []
