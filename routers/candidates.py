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
    create_candidate,
    create_run,
    delete_candidate,
    finish_run,
    get_default_cutoff,
    list_candidate_groups,
    list_candidate_keywords,
    list_candidate_status_counts,
    parse_pub_date,
    remove_candidate_keyword,
    reject_candidate,
    recluster_pending_candidates,
    restore_rejected_candidate,
    restore_candidate_auto_grouping,
    restore_covered_candidate,
    set_candidate_representative,
    to_iso,
    ungroup_candidate,
)
from services.news_service import fetch_news, get_naver_api_headers


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

    items = list_candidate_groups(status=status)
    return {
        "items": items,
        "group_count": len(items),
        "article_count": sum(int(item.get("cluster_size") or 1) for item in items),
        "related_article_count": sum(int(item.get("related_count") or 0) for item in items),
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
    created_count = 0
    total_checked = 0
    skipped_low_score = 0
    skipped_finalized = 0
    skipped_duplicate = 0

    for keyword in keywords:
        start = 1
        for _ in range(5):
            items = await fetch_news(keyword, headers=headers, start=start, display=100)
            if not items:
                break

            total_checked += len(items)
            reached_cutoff = False
            for item in items:
                pub_dt = parse_pub_date(item.pubDate)
                if pub_dt and pub_dt < cutoff:
                    reached_cutoff = True
                    continue

                result = await create_candidate(item, keyword)
                if result["created"]:
                    created_count += 1
                elif result["status"] == "low_score":
                    skipped_low_score += 1
                elif result["status"] == "finalized":
                    skipped_finalized += 1
                elif result["status"] == "duplicate":
                    skipped_duplicate += 1

            if reached_cutoff:
                break

            start += 100

    finish_run(run_id, created_count)
    cluster_summary = recluster_pending_candidates()
    return {
        "status": "success",
        "created": created_count,
        "checked": total_checked,
        "skipped_low_score": skipped_low_score,
        "skipped_finalized": skipped_finalized,
        "skipped_duplicate": skipped_duplicate,
        "cutoff": cutoff.isoformat(),
        "keywords": keywords,
        "cleanup_deleted": cleanup_deleted,
        "cluster_summary": cluster_summary,
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


@router.post("/clipping-candidates/{candidate_id}/representative")
async def set_clipping_candidate_representative(request: Request, candidate_id: int):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    if not set_candidate_representative(candidate_id):
        return JSONResponse(content={"error": "Pending candidate not found"}, status_code=404)

    return {"status": "success"}


@router.post("/clipping-candidates/{candidate_id}/ungroup")
async def ungroup_clipping_candidate(request: Request, candidate_id: int):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    if not ungroup_candidate(candidate_id):
        return JSONResponse(content={"error": "Pending candidate not found"}, status_code=404)

    return {"status": "success"}


@router.post("/clipping-candidates/{candidate_id}/restore-grouping")
async def restore_clipping_candidate_grouping(request: Request, candidate_id: int):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    if not restore_candidate_auto_grouping(candidate_id):
        return JSONResponse(content={"error": "Pending candidate not found"}, status_code=404)

    return {"status": "success"}


@router.post("/clipping-candidates/{candidate_id}/restore")
async def restore_clipping_candidate(request: Request, candidate_id: int):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    if not restore_rejected_candidate(candidate_id):
        return JSONResponse(content={"error": "Rejected candidate not found"}, status_code=404)

    return {"status": "success"}


@router.post("/clipping-candidates/{candidate_id}/restore-covered")
async def restore_covered_clipping_candidate(request: Request, candidate_id: int):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    if not restore_covered_candidate(candidate_id):
        return JSONResponse(content={"error": "Covered candidate not found"}, status_code=404)

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
