"""Human-review queue endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep, Principal, Reviewer, Viewer
from app.api.schemas import (
    ReviewCorrectionRequest,
    ReviewDecisionRequest,
    ReviewListResponse,
    ReviewResponse,
)
from app.domain.enums import ReviewStatus

router = APIRouter(prefix="/reviews", tags=["reviews"])


def _reviewer_id(principal: Principal, body: ReviewDecisionRequest) -> str:
    # With auth enabled the identity comes from the credential, never from the request body.
    if principal.authenticated:
        return principal.principal_id
    return body.reviewer_id or "local-reviewer"


@router.get("", response_model=ReviewListResponse)
def list_reviews(
    container: ContainerDep,
    _: Viewer,
    status: ReviewStatus | None = None,
    document_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReviewListResponse:
    items = container.reviews.list(
        status=status, document_id=document_id, limit=limit, offset=offset
    )
    return ReviewListResponse(
        items=[ReviewResponse.from_domain(r) for r in items], count=len(items)
    )


@router.get("/{review_id}", response_model=ReviewResponse)
def get_review(review_id: str, container: ContainerDep, _: Viewer) -> ReviewResponse:
    return ReviewResponse.from_domain(container.reviews.get(review_id))


@router.post("/{review_id}/approve", response_model=ReviewResponse)
def approve_review(
    review_id: str, body: ReviewDecisionRequest, container: ContainerDep, principal: Reviewer
) -> ReviewResponse:
    case = container.reviews.approve(review_id, _reviewer_id(principal, body), body.comment)
    return ReviewResponse.from_domain(case)


@router.post("/{review_id}/reject", response_model=ReviewResponse)
def reject_review(
    review_id: str, body: ReviewDecisionRequest, container: ContainerDep, principal: Reviewer
) -> ReviewResponse:
    case = container.reviews.reject(review_id, _reviewer_id(principal, body), body.comment)
    return ReviewResponse.from_domain(case)


@router.post("/{review_id}/correct", response_model=ReviewResponse)
def correct_review(
    review_id: str, body: ReviewCorrectionRequest, container: ContainerDep, principal: Reviewer
) -> ReviewResponse:
    case = container.reviews.correct(
        review_id, _reviewer_id(principal, body), body.corrections, body.comment
    )
    return ReviewResponse.from_domain(case)
