from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app_logging import get_logger
from routers.auth import require_auth
from services.clipping_store import (
    delete_finalization,
    get_finalization,
    list_finalizations,
    record_clip_event,
    save_final_clipping_snapshot,
    update_finalization,
)
from services.storage_backup import BackupConfigError
from services.storage_orchestrator import create_storage_backup_result


logger = get_logger("routers.clippings")
router = APIRouter(prefix="/api")


class ClipEventRequest(BaseModel):
    title: str
    link: str
    original_link: str = ""
    source: str = ""
    pub_date: str = ""
    category: str = "기타"


class FinalClippingRequest(BaseModel):
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


@router.post("/clipping-events")
async def clipping_events(request: Request, data: ClipEventRequest):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    record_clip_event(
        title=data.title,
        link=data.link,
        original_link=data.original_link,
        source=data.source,
        pub_date=data.pub_date,
        category=data.category,
        action="draft",
    )
    return {"status": "success"}


@router.post("/clipping-finalizations")
async def clipping_finalizations(request: Request, data: FinalClippingRequest):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    result = await save_final_clipping_snapshot(data.content)
    response = {"status": "success", **result}

    if result.get("duplicate"):
        return response

    return await _attach_auto_backup(response, "finalization create")


@router.get("/clipping-finalizations")
async def get_clipping_finalizations(request: Request, limit: int = 30):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    return {"status": "success", "items": list_finalizations(limit=limit)}


@router.get("/clipping-finalizations/{snapshot_id}")
async def get_clipping_finalization(request: Request, snapshot_id: int):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    item = get_finalization(snapshot_id)
    if not item:
        return JSONResponse(content={"error": "Finalization not found"}, status_code=404)
    return {"status": "success", "item": item}


@router.put("/clipping-finalizations/{snapshot_id}")
async def update_clipping_finalization(request: Request, snapshot_id: int, data: FinalClippingRequest):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    result = update_finalization(snapshot_id, data.content)
    if result.get("reason") == "not_found":
        return JSONResponse(content={"error": "Finalization not found"}, status_code=404)
    if result.get("duplicate"):
        return JSONResponse(content={"error": "Same finalization already exists", **result}, status_code=409)

    response = {"status": "success", **result}
    return await _attach_auto_backup(response, "finalization update")


@router.delete("/clipping-finalizations/{snapshot_id}")
async def remove_clipping_finalization(request: Request, snapshot_id: int):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    success = delete_finalization(snapshot_id)
    response = {"status": "success", "deleted": success}
    if success:
        return await _attach_auto_backup(response, "finalization delete")
    return response
