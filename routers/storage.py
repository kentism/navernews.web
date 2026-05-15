from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.clipping_store import (
    export_storage_snapshot,
    get_storage_status,
    import_storage_snapshot,
)
from services.storage_backup import (
    BackupConfigError,
    download_backup,
    get_backup_config_status,
)
from services.storage_orchestrator import create_storage_backup_result
from routers.auth import require_auth


router = APIRouter(prefix="/api/storage")


class StorageImportRequest(BaseModel):
    payload: dict
    confirm_replace: bool = False


class StorageRestoreRequest(BaseModel):
    confirm_replace: bool = False


@router.get("/status")
async def storage_status(request: Request):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    return {
        "status": "success",
        "storage": get_storage_status(),
        "backup": get_backup_config_status(),
    }


@router.get("/export")
async def storage_export(request: Request):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    return {"status": "success", "snapshot": export_storage_snapshot()}


@router.post("/import")
async def storage_import(request: Request, data: StorageImportRequest):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    if not data.confirm_replace:
        return JSONResponse(
            content={"error": "confirm_replace must be true to replace local storage."},
            status_code=400,
        )

    try:
        result = import_storage_snapshot(data.payload, replace=True)
    except ValueError as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=400)

    return {"status": "success", **result}


@router.get("/backup/status")
async def storage_backup_status(request: Request):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    return {"status": "success", "backup": get_backup_config_status()}


@router.post("/backup")
async def storage_backup(request: Request):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    try:
        result = await create_storage_backup_result()
    except BackupConfigError as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=502)

    return {"status": "success", **result}


@router.post("/restore")
async def storage_restore(request: Request, data: StorageRestoreRequest):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    if not data.confirm_replace:
        return JSONResponse(
            content={"error": "confirm_replace must be true to restore backup over local storage."},
            status_code=400,
        )

    try:
        snapshot = await download_backup()
        result = import_storage_snapshot(snapshot, replace=True)
    except BackupConfigError as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=400)
    except FileNotFoundError as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=404)
    except ValueError as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=502)

    return {"status": "success", **result}
