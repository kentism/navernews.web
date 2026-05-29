from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app_logging import get_logger
from routers.auth import require_auth
from services.candidate_collector import collect_candidates
from services.clipping_store import cleanup_stale_pending_candidates, save_final_clipping_snapshot
from services.dashboard_service import (
    build_dashboard_payload,
    get_dashboard_keywords,
    get_dashboard_window,
)
from services.news_service import get_naver_api_headers
from services.storage_backup import BackupConfigError
from services.storage_orchestrator import create_storage_backup_result


logger = get_logger("routers.dashboard")
router = APIRouter(prefix="/api/dashboard")


class DashboardFinalizeRequest(BaseModel):
    content: str


async def _attach_auto_backup(response: dict, action: str) -> dict:
    try:
        response["auto_backup"] = await create_storage_backup_result()
    except BackupConfigError as exc:
        response["backup_warning"] = str(exc)
        logger.warning(f"Automatic backup skipped after {action}", extra={"error": str(exc)})
    except RuntimeError as exc:
        response["backup_warning"] = str(exc)
        logger.warning(f"Automatic backup failed after {action}", extra={"error": str(exc)})
    return response


@router.post("/run")
async def run_dashboard(
    request: Request,
    extra_keywords: str = Form(default=""),
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

    extra = [keyword.strip() for keyword in extra_keywords.split(",") if keyword.strip()]
    keywords = get_dashboard_keywords(extra)
    if not keywords:
        return JSONResponse(content={"error": "Dashboard keywords are missing"}, status_code=400)

    cleanup_deleted = cleanup_stale_pending_candidates()
    window = get_dashboard_window()
    collection = await collect_candidates(
        keywords=keywords,
        headers=headers,
        cutoff=window["start"],
        until=window["end"],
    )
    dashboard = build_dashboard_payload(
        candidates=collection["candidates"],
        keywords=keywords,
        window=window,
        collection=collection,
    )

    return {
        "status": "success",
        "cleanup_deleted": cleanup_deleted,
        "dashboard": dashboard,
    }


@router.post("/finalize")
async def finalize_dashboard(request: Request, data: DashboardFinalizeRequest):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    content = data.content.strip()
    if not content:
        return JSONResponse(content={"error": "Final content is required"}, status_code=400)

    result = await save_final_clipping_snapshot(content)
    response = {"status": "success", **result}
    if result.get("duplicate"):
        return response

    return await _attach_auto_backup(response, "dashboard finalization create")
