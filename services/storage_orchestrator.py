from services.clipping_store import export_storage_snapshot
from services.storage_backup import upload_backup


async def create_storage_backup_result() -> dict:
    snapshot = export_storage_snapshot()
    backup = await upload_backup(snapshot)
    return {"backup": backup, "storage": snapshot["storage"]}
