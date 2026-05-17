from app_logging import get_logger
from services.clipping_store import (
    export_storage_snapshot,
    get_learning_summary,
    get_storage_status,
    import_storage_snapshot,
)
from services.storage_backup import (
    BackupConfigError,
    download_backup,
    get_backup_config_status,
    is_backup_configured,
    upload_backup,
)


logger = get_logger("services.storage_orchestrator")


def summarize_backup_snapshot(snapshot: dict) -> dict:
    tables = snapshot.get("tables") if isinstance(snapshot, dict) else {}
    tables = tables if isinstance(tables, dict) else {}
    finalizations = tables.get("final_clipping_snapshots") or []
    events = tables.get("clipping_events") or []
    candidates = tables.get("clipping_candidates") or []

    latest_snapshot = None
    for item in finalizations:
        if not isinstance(item, dict):
            continue
        created_at = item.get("created_at")
        if created_at and (latest_snapshot is None or created_at > latest_snapshot.get("created_at", "")):
            latest_snapshot = item

    finalized_events = [
        item for item in events
        if isinstance(item, dict) and item.get("action") == "finalized"
    ]

    return {
        "available": True,
        "exported_at": snapshot.get("exported_at"),
        "snapshot_count": len(finalizations),
        "finalized_event_count": len(finalized_events),
        "candidate_count": len(candidates),
        "last_finalized_at": latest_snapshot.get("created_at") if latest_snapshot else None,
        "last_snapshot_entry_count": int(latest_snapshot.get("entry_count") or 0) if latest_snapshot else 0,
    }


async def create_storage_backup_result() -> dict:
    snapshot = export_storage_snapshot()
    backup = await upload_backup(snapshot)
    return {"backup": backup, "storage": snapshot["storage"], "learning": get_learning_summary()}


async def inspect_backup_learning_summary() -> dict:
    if not is_backup_configured():
        return {"available": False, "reason": "backup_not_configured"}

    snapshot = await download_backup()
    return summarize_backup_snapshot(snapshot)


async def restore_backup_result() -> dict:
    snapshot = await download_backup()
    backup_summary = summarize_backup_snapshot(snapshot)
    result = import_storage_snapshot(snapshot, replace=True)
    return {
        "restore": result,
        "backup_learning": backup_summary,
        "storage": get_storage_status(),
        "learning": get_learning_summary(),
    }


async def restore_backup_if_local_learning_empty() -> dict:
    current_learning = get_learning_summary()
    if current_learning["snapshot_count"] > 0 or current_learning["finalized_event_count"] > 0:
        return {
            "status": "skipped",
            "reason": "local_learning_present",
            "learning": current_learning,
            "backup": get_backup_config_status(),
        }

    if not is_backup_configured():
        return {
            "status": "skipped",
            "reason": "backup_not_configured",
            "learning": current_learning,
            "backup": get_backup_config_status(),
        }

    try:
        snapshot = await download_backup()
        backup_summary = summarize_backup_snapshot(snapshot)
    except (BackupConfigError, FileNotFoundError, ValueError, RuntimeError) as exc:
        logger.warning("Learning backup auto-restore inspection failed", extra={"error": str(exc)})
        return {
            "status": "failed",
            "reason": "backup_inspection_failed",
            "error": str(exc),
            "learning": current_learning,
            "backup": get_backup_config_status(),
        }

    if backup_summary["snapshot_count"] <= 0 and backup_summary["finalized_event_count"] <= 0:
        return {
            "status": "skipped",
            "reason": "backup_has_no_learning",
            "learning": current_learning,
            "backup_learning": backup_summary,
            "backup": get_backup_config_status(),
        }

    try:
        result = import_storage_snapshot(snapshot, replace=True)
    except ValueError as exc:
        logger.warning("Learning backup auto-restore failed", extra={"error": str(exc)})
        return {
            "status": "failed",
            "reason": "restore_failed",
            "error": str(exc),
            "learning": current_learning,
            "backup_learning": backup_summary,
            "backup": get_backup_config_status(),
        }

    restored_learning = get_learning_summary()
    logger.info(
        "Learning backup auto-restored",
        extra={
            "snapshot_count": restored_learning["snapshot_count"],
            "finalized_event_count": restored_learning["finalized_event_count"],
        },
    )
    return {
        "status": "restored",
        "reason": "local_learning_empty",
        "restore": result,
        "learning": restored_learning,
        "backup_learning": backup_summary,
        "backup": get_backup_config_status(),
    }
