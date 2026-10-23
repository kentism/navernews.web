import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from routers.auth import require_auth
from services.legacy_archive import inspect_legacy_archive

router = APIRouter(prefix="/api/storage")


@router.get("/status")
async def storage_status(request: Request):
    auth = await require_auth(request)
    if auth:
        return auth
    try:
        archive = inspect_legacy_archive()
    except (OSError, sqlite3.Error):
        return JSONResponse({"error": "이전 이력 파일을 읽지 못했습니다."}, status_code=503)
    return {"status": "success", "draft_storage": "browser", "learning_enabled": False,
            "legacy_archive": archive}


@router.get("/export")
async def storage_export(request: Request):
    auth = await require_auth(request)
    if auth:
        return auth
    try:
        snapshot = inspect_legacy_archive(include_rows=True)
    except (OSError, sqlite3.Error):
        return JSONResponse({"error": "이전 이력 내보내기에 실패했습니다."}, status_code=503)
    return JSONResponse({"status": "success", "snapshot": snapshot}, headers={
        "Content-Disposition": 'attachment; filename="legacy-clipping-archive.json"'})
