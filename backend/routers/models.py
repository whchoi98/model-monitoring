"""Router for listing available Bedrock models."""

from __future__ import annotations

from fastapi import APIRouter

from prober import AVAILABLE_MODELS
from schemas import ModelInfo

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=list[ModelInfo])
def list_models():
    """Return the hardcoded list of all available Bedrock models."""
    return [
        ModelInfo(id=model_id, name=model_name)
        for model_id, model_name in AVAILABLE_MODELS.items()
    ]
