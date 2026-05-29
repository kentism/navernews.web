from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app_logging import get_logger
from routers.auth import require_auth
from services.clipping_store import (
    DEFAULT_CATEGORIES,
    CANDIDATE_PENDING_RETENTION_DAYS,
    accept_candidate,
    add_candidate_keyword,
    cleanup_stale_pending_candidates,
    clear_pending_candidates,
    create_run,
    delete_candidate,
    finish_run,
    get_default_cutoff,
    list_candidates,
    list_candidate_keywords,
    list_candidate_status_counts,
    remove_candidate_keyword,
    reject_candidate,
    restore_rejected_candidate,
    to_iso,
)
from services.candidate_collector import collect_candidates
from services.news_service import get_naver_api_headers


logger = get_logger("routers.candidates")
router = APIRouter(prefix="/api")
ALLOWED_CANDIDATE_STATUSES = {"pending", "accepted", "rejected"}


class CandidateKeywordRequest(BaseModel):
    keyword: str


class CandidateDecisionRequest(BaseModel):
    category: Optional[str] = None


@router.get("/clipping-candidates")
async def clipping_candidates(request: Request, status: str = "pending"):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check
    if status not in ALLOWED_CANDIDATE_STATUSES:
        return JSONResponse(content={"error": "Invalid candidate status"}, status_code=400)

    cleanup_deleted = cleanup_stale_pending_candidates()

    return {
        "items": list_candidates(status=status),
        "status_counts": list_candidate_status_counts(),
        "cleanup_deleted": cleanup_deleted,
        "pending_retention_days": CANDIDATE_PENDING_RETENTION_DAYS,
        "categories": DEFAULT_CATEGORIES,
        "keywords": list_candidate_keywords(),
        "default_cutoff": to_iso(get_default_cutoff()),
    }


@router.get("/candidate-keywords")
async def candidate_keywords(request: Request):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    return {"items": list_candidate_keywords()}


@router.post("/candidate-keywords")
async def add_candidate_keyword_api(request: Request, data: CandidateKeywordRequest):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    keyword = data.keyword.strip()
    if not keyword:
        return JSONResponse(content={"error": "Keyword is required"}, status_code=400)

    created = add_candidate_keyword(keyword)
    return {"status": "success", "created": created, "items": list_candidate_keywords()}


@router.post("/candidate-keywords/remove")
async def remove_candidate_keyword_api(request: Request, data: CandidateKeywordRequest):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    removed = remove_candidate_keyword(data.keyword)
    return {"status": "success", "removed": removed, "items": list_candidate_keywords()}


@router.post("/clipping-candidates/run")
async def run_clipping_candidates(
    request: Request,
    since: str = Form(default=""),
    headers: dict = Depends(get_naver_api_headers),
):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check
    if not headers.get("X-Naver-Client-Id") or not headers.get("X-Naver-Client-Secret"):
        return JSONResponse(
            content={"error": "Naver API credentials are missing"},
            status_code=400,
        )

    cutoff = get_default_cutoff()
    if since:
        try:
            if since == "today":
                cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            elif since == "24h":
                cutoff = datetime.now(timezone.utc) - timedelta(days=1)
            elif since == "3d":
                cutoff = datetime.now(timezone.utc) - timedelta(days=3)
            else:
                cutoff = datetime.fromisoformat(since).astimezone(timezone.utc)
        except Exception as exc:
            logger.warning(f"Invalid since value: {since}, error: {exc}")

    keywords = list_candidate_keywords()
    if not keywords:
        return {
            "status": "success",
            "created": 0,
            "cutoff": cutoff.isoformat(),
            "keywords": [],
            "message": "No candidate keywords configured",
        }

    cleanup_deleted = cleanup_stale_pending_candidates()
    run_id = create_run(cutoff, keywords)
    collection = await collect_candidates(keywords=keywords, headers=headers, cutoff=cutoff)

    finish_run(run_id, collection["created"])
    return {
        "status": "success",
        "created": collection["created"],
        "checked": collection["checked"],
        "skipped_low_score": collection["skipped_low_score"],
        "skipped_finalized": collection["skipped_finalized"],
        "skipped_duplicate": collection["skipped_duplicate"],
        "cutoff": cutoff.isoformat(),
        "keywords": keywords,
        "cleanup_deleted": cleanup_deleted,
    }


@router.post("/clipping-candidates/{candidate_id}/accept")
async def accept_clipping_candidate(request: Request, candidate_id: int, data: CandidateDecisionRequest):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    candidate = accept_candidate(candidate_id, data.category)
    if not candidate:
        return JSONResponse(content={"error": "Candidate not found"}, status_code=404)

    return {"status": "success", "item": candidate}


@router.post("/clipping-candidates/{candidate_id}/reject")
async def reject_clipping_candidate(request: Request, candidate_id: int):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    if not reject_candidate(candidate_id):
        return JSONResponse(content={"error": "Candidate not found"}, status_code=404)

    return {"status": "success"}


@router.post("/clipping-candidates/{candidate_id}/restore")
async def restore_clipping_candidate(request: Request, candidate_id: int):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    if not restore_rejected_candidate(candidate_id):
        return JSONResponse(content={"error": "Rejected candidate not found"}, status_code=404)

    return {"status": "success"}


@router.post("/clipping-candidates/{candidate_id}/delete")
async def delete_clipping_candidate(request: Request, candidate_id: int):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    if not delete_candidate(candidate_id):
        return JSONResponse(content={"error": "Candidate not found"}, status_code=404)

    return {"status": "success"}


@router.post("/clipping-candidates/clear-pending")
async def clear_pending_clipping_candidates(request: Request):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    deleted = clear_pending_candidates()
    return {"status": "success", "deleted": deleted}
