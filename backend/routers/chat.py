"""챗봇 SSE 라우터 — POST /api/chat/stream.

흐름:
  1. 사용자 메시지를 AgentCore Memory에 기록 (best-effort).
  2. Bedrock Sonnet 4.6에 tools와 함께 converse_stream 호출.
  3. tool_use 받으면 즉시 tool 실행 후 tool_result로 다시 호출 (최대 N hop).
  4. text_delta는 그대로 SSE delta 이벤트로 emit.
  5. 종료/예외에 관계없이 'final' 이벤트 emit (try/finally).
  6. 어시스턴트 최종 응답을 AgentCore Memory에 기록.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import User
from agent import bedrock as bedrock_client
from agent import memory as memory_client
from agent import tools as tools_module
from agent.streaming import sse_event, stream_with_final

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

# 같은 채팅에서 tool_use → tool_result hop 한도 — 무한 루프 방지.
MAX_TOOL_HOPS = 4


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: Optional[str] = None  # 사용자가 명시 시 그 세션, 아니면 신규.


# Bedrock Converse API tool 스펙.
_TOOL_SPECS = [
    bedrock_client.tool_spec_for(
        name="get_latest_results",
        description="모니터링 대상 모델들의 최신 자동 프로브 결과를 반환한다.",
        input_schema={
            "type": "object",
            "properties": {
                "model_id": {
                    "type": "string",
                    "description": "특정 model_id로 한정. 미지정 시 모든 모델.",
                },
            },
        },
    ),
    bedrock_client.tool_spec_for(
        name="get_trend",
        description="최근 N시간 동안의 시계열 추세를 반환한다.",
        input_schema={
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "minimum": 1, "maximum": 168, "default": 24},
                "metric": {
                    "type": "string",
                    "enum": ["ttft_ms", "total_latency_ms", "tps"],
                    "default": "ttft_ms",
                },
            },
        },
    ),
    bedrock_client.tool_spec_for(
        name="compare_models",
        description="최근 N시간 동안의 모델별 metric 통계 (avg/p50/p95)를 반환한다.",
        input_schema={
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": ["ttft_ms", "total_latency_ms", "tps"],
                    "default": "ttft_ms",
                },
                "hours": {"type": "integer", "minimum": 1, "maximum": 168, "default": 24},
            },
        },
    ),
    bedrock_client.tool_spec_for(
        name="optimize_prompt",
        description="사용자가 제공한 프롬프트를 최적화하기 위한 가이드라인을 반환한다.",
        input_schema={
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "target": {"type": "string", "default": "shorter_with_same_quality"},
            },
            "required": ["prompt"],
        },
    ),
]


def _invoke_tool(name: str, tool_input: dict, db: Session) -> dict:
    """tool name → 함수 매핑 후 실행. DB 필요 여부는 함수별로 처리."""
    fn = tools_module.TOOL_REGISTRY.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    try:
        if name == "optimize_prompt":
            return fn(**tool_input)
        return fn(db, **tool_input)
    except TypeError as exc:
        return {"error": f"bad tool input: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("tool '%s' 실행 실패", name)
        return {"error": str(exc)}


async def _generate_followups(user_question: str, assistant_answer: str) -> list[str]:
    """대화 맥락 기반 follow-up 3개 생성 — 응답에 등장한 모델·메트릭·시간대 참조.

    Haiku 4.5로 빠르고 저렴하게. 응답이 JSON array가 아닐 경우 line 단위 fallback.
    """
    import json as _json
    import re as _re
    from agent.bedrock import converse_blocking

    system = (
        "You are a follow-up question generator for a Bedrock LLM monitoring chatbot. "
        "Given the user's last question and the assistant's answer, output 3 concise follow-up questions "
        "the user would naturally ask next. Questions must reference SPECIFIC entities mentioned "
        "(model names, metrics, time windows, errors). Keep each under 25 words. "
        "Respond in the SAME language as the answer. "
        "Output ONLY a JSON array of 3 strings, no preamble. Example: "
        '[\"Question 1\", \"Question 2\", \"Question 3\"]'
    )
    user_prompt = (
        f"User question:\n{user_question[:500]}\n\n"
        f"Assistant answer:\n{assistant_answer[:2000]}\n\n"
        "Generate 3 follow-up questions as a JSON array."
    )

    raw = converse_blocking(
        messages=[{"role": "user", "content": [{"text": user_prompt}]}],
        model_id="global.anthropic.claude-haiku-4-5-20251001-v1:0",
        system=system,
        max_tokens=400,
        temperature=0.4,
    )

    # JSON array 추출 — 응답이 ```json ... ``` 또는 prefix 포함 가능.
    match = _re.search(r"\[\s*\".*?\"\s*\]", raw, _re.DOTALL)
    if match:
        try:
            arr = _json.loads(match.group(0))
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()][:3]
        except _json.JSONDecodeError:
            pass

    # Fallback: 줄 단위로 ?로 끝나는 line 추출.
    lines = [ln.strip(" -*0123456789.") for ln in raw.splitlines()]
    cands = [ln for ln in lines if ln and (ln.endswith("?") or "?" in ln)]
    return cands[:3]


async def _chat_generator(
    initial_message: str,
    actor_id: str,
    session_id: str,
    db: Session,
) -> AsyncIterator[str]:
    """Bedrock + tool loop를 SSE 청크 생성기로 변환."""
    # 1) 사용자 메시지 emit (immediate ack).
    yield sse_event(
        "user",
        {"role": "USER", "content": initial_message, "session_id": session_id},
    )

    # AgentCore Memory에 user 메시지 기록.
    memory_client.append_message(actor_id, session_id, role="USER", content=initial_message)

    # 2) 메시지 빌드 — 과거 컨텍스트는 AgentCore Memory에서 회수.
    history = memory_client.list_recent_messages(actor_id, session_id, limit=20)
    messages: List[Dict] = []
    for h in history:
        messages.append(
            {
                "role": "user" if h["role"] == "USER" else "assistant",
                "content": [{"text": h["content"]}],
            }
        )
    if not messages or messages[-1]["content"][0]["text"] != initial_message:
        messages.append({"role": "user", "content": [{"text": initial_message}]})

    assistant_buffer: List[str] = []

    # 3) Bedrock 호출 loop — tool_use → tool_result → 다시 호출.
    for hop in range(MAX_TOOL_HOPS + 1):
        text_acc: List[str] = []
        tool_uses: List[dict] = []
        stop_reason: Optional[str] = None

        async for ev in bedrock_client.converse_stream_chat(
            messages=messages,
            tools=_TOOL_SPECS,
            max_tokens=1024,
        ):
            t = ev.get("type")
            if t == "text_delta":
                text = ev["text"]
                text_acc.append(text)
                yield sse_event("delta", {"text": text})
            elif t == "tool_use":
                tool_uses.append(ev["tool_use"])
            elif t == "stop":
                stop_reason = ev.get("stop_reason")
            elif t == "error":
                yield sse_event("error", {"message": ev.get("error", "unknown")})
                return
            elif t == "usage":
                yield sse_event("usage", ev.get("usage", {}))

        text_full = "".join(text_acc)
        if text_full:
            assistant_buffer.append(text_full)

        if stop_reason != "tool_use" or not tool_uses:
            break

        # tool_use 응답을 messages에 assistant turn으로 추가.
        assistant_content: List[Dict] = []
        if text_full:
            assistant_content.append({"text": text_full})
        for tu in tool_uses:
            assistant_content.append(
                {
                    "toolUse": {
                        "toolUseId": tu["toolUseId"],
                        "name": tu["name"],
                        "input": tu["input"],
                    }
                }
            )
        messages.append({"role": "assistant", "content": assistant_content})

        # 각 tool을 실행하고 tool_result 빌드.
        tool_results_content: List[Dict] = []
        for tu in tool_uses:
            yield sse_event(
                "tool_call",
                {"name": tu["name"], "input": tu["input"], "toolUseId": tu["toolUseId"]},
            )
            result = _invoke_tool(tu["name"], tu["input"], db)
            tool_results_content.append(
                {
                    "toolResult": {
                        "toolUseId": tu["toolUseId"],
                        "content": [{"json": result}],
                    }
                }
            )
        messages.append({"role": "user", "content": tool_results_content})

        if hop == MAX_TOOL_HOPS:
            yield sse_event(
                "warning",
                {"message": f"MAX_TOOL_HOPS({MAX_TOOL_HOPS}) 도달, 종료"},
            )
            break

    # 4) Memory에 assistant 최종 응답 기록.
    final_assistant = "".join(assistant_buffer).strip()
    if final_assistant:
        memory_client.append_message(
            actor_id, session_id, role="ASSISTANT", content=final_assistant
        )

    # 5) 동적 Follow-up 3개 생성 — 마지막 user 질문 + assistant 응답을 기반으로 Haiku 4.5에 single-shot.
    #    응답이 너무 짧거나 에러면 skip.
    if final_assistant and len(final_assistant) >= 20:
        try:
            followups = await _generate_followups(initial_message, final_assistant)
            if followups:
                yield sse_event("followups", {"suggestions": followups})
        except Exception:
            logger.exception("Followup generation failed (non-fatal)")


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE 스트리밍 챗봇 엔드포인트 (인증 필요)."""
    session_id = body.session_id or f"chat-{user.username}-{uuid.uuid4().hex[:12]}"
    actor_id = f"user-{user.username}"

    async def inner():
        async for chunk in _chat_generator(body.message, actor_id, session_id, db):
            yield chunk

    final_meta = {"session_id": session_id, "username": user.username}
    return StreamingResponse(
        stream_with_final(inner(), label="chat", on_error_metadata=final_meta),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx/ALB 버퍼링 방지
            "Connection": "keep-alive",
        },
    )


# 미사용 import 경고 회피용 (Optional 등은 동적으로 사용됨).
_ = json
