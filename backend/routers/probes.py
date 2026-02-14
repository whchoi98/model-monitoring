"""Router for probe execution and retrieval."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from auth import get_current_user
from database import get_db
from models import ProbeRun, User
from prober import AVAILABLE_MODELS, stream_probe_events
from schemas import ProbeRunRequest, ProbeRunResponse

router = APIRouter(prefix="/api/probes", tags=["probes"])


@router.post("/run")
def run_probe(request: ProbeRunRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Launch a new probe run and return results as an SSE stream.

    The response is a text/event-stream with the following event types:
      - start:  run metadata (run_id, total_tasks)
      - token:  individual output token from a model
      - ttft:   time-to-first-token measurement
      - result: full result object for one model/iteration
      - error:  error encountered during probing
      - complete: all tasks finished
    """
    # Validate model IDs
    invalid_ids = [mid for mid in request.model_ids if mid not in AVAILABLE_MODELS]
    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model IDs: {invalid_ids}",
        )

    if not request.model_ids:
        raise HTTPException(status_code=400, detail="At least one model_id is required")

    # Create the probe run record
    run = ProbeRun(
        prompt=request.prompt,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        concurrency=request.concurrency,
        repeat_count=request.repeat_count,
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    event_gen = stream_probe_events(
        model_ids=request.model_ids,
        prompt=request.prompt,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        concurrency=request.concurrency,
        repeat_count=request.repeat_count,
        db=db,
        run_id=run.id,
    )

    return StreamingResponse(
        event_gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{run_id}", response_model=ProbeRunResponse)
def get_probe_run(run_id: int, db: Session = Depends(get_db)):
    """Retrieve a past probe run by its ID, including all results."""
    run = db.query(ProbeRun).filter(ProbeRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Probe run not found")
    return run
