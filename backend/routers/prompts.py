"""Router for managing saved prompt sets + Bedrock Prompt Optimization."""

from __future__ import annotations

import logging
import os
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import PromptSet, User
from schemas import PromptSetCreate, PromptSetResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

# Bedrock Prompt Optimization은 bedrock-agent-runtime의 OptimizePrompt API.
# 지원 region 일부만 가능 - us-east-1을 기본으로 사용.
_OPTIMIZE_REGION = os.environ.get("BEDROCK_OPTIMIZE_REGION", "us-east-1")
_optimize_client_cache: object | None = None


def _get_optimize_client():
    global _optimize_client_cache
    if _optimize_client_cache is None:
        _optimize_client_cache = boto3.client(
            "bedrock-agent-runtime", region_name=_OPTIMIZE_REGION,
        )
    return _optimize_client_cache


class OptimizePromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=20000)
    target_model_id: str = Field(..., min_length=1, max_length=200)


class OptimizePromptResponse(BaseModel):
    analyze_message: Optional[str] = None
    optimized_prompt: Optional[str] = None
    target_model_id: str
    request_id: Optional[str] = None


@router.get("", response_model=list[PromptSetResponse])
def list_prompt_sets(db: Session = Depends(get_db)):
    """List all saved prompt sets, ordered by creation date descending."""
    return (
        db.query(PromptSet)
        .order_by(PromptSet.created_at.desc())
        .all()
    )


@router.post("", response_model=PromptSetResponse, status_code=201)
def create_prompt_set(payload: PromptSetCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a new prompt set.

    The name must be unique. Prompts is a list of prompt strings.
    """
    existing = db.query(PromptSet).filter(PromptSet.name == payload.name).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Prompt set with name '{payload.name}' already exists",
        )

    prompt_set = PromptSet(
        name=payload.name,
        prompts=payload.prompts,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
    )
    db.add(prompt_set)
    db.commit()
    db.refresh(prompt_set)
    return prompt_set


@router.delete("/{prompt_set_id}", status_code=204)
def delete_prompt_set(prompt_set_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a prompt set by its ID."""
    prompt_set = db.query(PromptSet).filter(PromptSet.id == prompt_set_id).first()
    if not prompt_set:
        raise HTTPException(status_code=404, detail="Prompt set not found")

    db.delete(prompt_set)
    db.commit()
    return None


def _normalize_target_model_id(model_id: str) -> str:
    """Inference profile ID → foundation-model ID 변환.

    OptimizePrompt API는 cross-region inference profile ID(`global.*`, `us.*`)를 받지 않음
    → 첫 prefix 제거해 plain foundation-model ID로 시도.
    예: `global.anthropic.claude-opus-4-7` → `anthropic.claude-opus-4-7`
        `us.amazon.nova-2-lite-v1:0` → `amazon.nova-2-lite-v1:0`
    이미 plain ID면 그대로.
    """
    parts = model_id.split(".", 1)
    if len(parts) == 2 and parts[0] in ("global", "us", "eu", "apac"):
        return parts[1]
    return model_id


@router.post("/optimize", response_model=OptimizePromptResponse)
def optimize_prompt(
    payload: OptimizePromptRequest,
    user: User = Depends(get_current_user),
):
    """Bedrock Simple Prompt Optimization (OptimizePrompt API).

    bedrock-agent-runtime.optimize_prompt 호출 → analyzePromptEvent + optimizedPromptEvent
    event stream을 한 번에 모아 JSON으로 반환 (UI는 동기 호출).
    """
    client = _get_optimize_client()
    normalized_id = _normalize_target_model_id(payload.target_model_id)
    try:
        response = client.optimize_prompt(
            input={"textPrompt": {"text": payload.prompt}},
            targetModelId=normalized_id,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        msg = exc.response.get("Error", {}).get("Message", str(exc))
        logger.warning("OptimizePrompt failed: %s - %s", code, msg)
        raise HTTPException(status_code=502, detail=f"{code}: {msg}")
    except Exception as exc:
        logger.exception("OptimizePrompt unexpected error")
        raise HTTPException(status_code=500, detail=str(exc))

    request_id = response.get("ResponseMetadata", {}).get("RequestId")
    analyze_message: Optional[str] = None
    optimized_text: Optional[str] = None
    try:
        for event in response.get("optimizedPrompt", []):
            if "analyzePromptEvent" in event:
                analyze_message = event["analyzePromptEvent"].get("message")
            elif "optimizedPromptEvent" in event:
                op = event["optimizedPromptEvent"].get("optimizedPrompt") or event["optimizedPromptEvent"]
                # 응답 구조: optimizedPrompt.textPrompt.text (또는 직접 message 형태)
                if isinstance(op, dict):
                    tp = op.get("textPrompt") or op.get("input", {}).get("textPrompt") or op
                    if isinstance(tp, dict):
                        optimized_text = tp.get("text") or tp.get("message")
                if not optimized_text:
                    optimized_text = str(op)
    except Exception:
        logger.exception("Failed to parse OptimizePrompt stream")
        raise HTTPException(status_code=500, detail="Failed to parse optimization stream")

    if not optimized_text:
        raise HTTPException(status_code=500, detail="No optimized prompt returned")

    return OptimizePromptResponse(
        analyze_message=analyze_message,
        optimized_prompt=optimized_text,
        target_model_id=payload.target_model_id,
        request_id=request_id,
    )
