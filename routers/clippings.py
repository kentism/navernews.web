from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app_logging import get_logger
from routers.auth import require_auth
from services.clipping_store import (
    delete_finalization,
    list_finalizations,
    record_clip_event,
    save_final_clipping_snapshot,
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

    try:
        response["auto_backup"] = await create_storage_backup_result()
    except BackupConfigError as exc:
        response["backup_warning"] = str(exc)
        logger.warning("Automatic backup skipped", extra={"error": str(exc)})
    except RuntimeError as exc:
        response["backup_warning"] = str(exc)
        logger.warning("Automatic backup failed", extra={"error": str(exc)})

    return response


@router.get("/clipping-finalizations")
async def get_clipping_finalizations(request: Request, limit: int = 30):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    return {"status": "success", "items": list_finalizations(limit=limit)}


@router.delete("/clipping-finalizations/{snapshot_id}")
async def remove_clipping_finalization(request: Request, snapshot_id: int):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    success = delete_finalization(snapshot_id)
    return {"status": "success", "deleted": success}
