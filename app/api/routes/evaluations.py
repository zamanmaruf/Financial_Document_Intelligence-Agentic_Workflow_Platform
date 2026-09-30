"""Evaluation endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import Admin, ContainerDep, Viewer
from app.domain.models import EvaluationResult
from app.evaluation.runner import EvaluationRunner

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.get("", response_model=list[EvaluationResult])
def list_evaluations(
    container: ContainerDep, _: Viewer, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[EvaluationResult]:
    return container.evaluations.recent(limit)


@router.post("/run", response_model=EvaluationResult)
def run_evaluation(container: ContainerDep, principal: Admin) -> EvaluationResult:
    """Run the labelled evaluation suite in an isolated sandbox and store the result.

    Synchronous by design for the small synthetic dataset; with a real provider this makes
    paid model calls (roughly 3 per document plus 1 per question).
    """
    result = EvaluationRunner(container.settings).run()
    container.evaluations.save(result)
    container.audit.record(
        "evaluation.completed",
        actor=principal.actor,
        details={
            "run_id": result.run_id,
            "gate_passed": result.gate_passed,
            "gate_failures": result.gate_failures,
            "is_mock": result.is_mock,
        },
    )
    return result
