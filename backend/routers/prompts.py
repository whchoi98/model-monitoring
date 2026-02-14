"""Router for managing saved prompt sets."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import PromptSet, User
from schemas import PromptSetCreate, PromptSetResponse

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


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
