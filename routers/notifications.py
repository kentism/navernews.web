import asyncio
from typing import List

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app_config import NOTIFICATION_HISTORY_TTL_SECONDS
from app_logging import get_logger
from routers.auth import require_auth
from services.monitoring import state


logger = get_logger("routers.notifications")
router = APIRouter(prefix="/api")


class SyncWatchRequest(BaseModel):
    client_id: str
    keywords: List[str]


def _current_loop_time() -> float:
    return asyncio.get_running_loop().time()


@router.get("/stream/notifications")
async def sse_notifications(request: Request, client_id: str = None):
    if not client_id:
        return JSONResponse(content={"error": "client_id is required"}, status_code=400)

    async def event_generator():
        current_time = _current_loop_time()
        state.last_seen_clients[client_id] = current_time

        queue = asyncio.Queue()
        state.sse_connections[client_id] = queue

        try:
            yield f"data: connected:{client_id}\n\n"

            client_keywords = [
                keyword
                for keyword, watchers in state.watch_registry.items()
                if client_id in watchers
            ]

            for ts, keyword, message in state.notification_history:
                if keyword in client_keywords and (current_time - ts) < NOTIFICATION_HISTORY_TTL_SECONDS:
                    yield f"data: {message}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {message}\n\n"
                    state.last_seen_clients[client_id] = _current_loop_time()
                except asyncio.TimeoutError:
                    yield "data: ping\n\n"
                    state.last_seen_clients[client_id] = _current_loop_time()
        except asyncio.CancelledError:
            logger.info("SSE connection cancelled", extra={"client_id": client_id})
        finally:
            state.sse_connections.pop(client_id, None)
            state.last_seen_clients[client_id] = _current_loop_time()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/watch")
async def watch_keyword(request: Request, keyword: str = Form(...), client_id: str = Form(None)):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    if not client_id:
        return JSONResponse({"status": "error", "message": "No client_id provided"}, status_code=400)

    state.watch_registry.setdefault(keyword, set()).add(client_id)
    logger.info("Registered keyword watch", extra={"client_id": client_id, "keyword": keyword})
    return {"status": "success", "keyword": keyword}


@router.post("/unwatch")
async def unwatch_keyword(request: Request, keyword: str = Form(...), client_id: str = Form(None)):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    if not client_id:
        return JSONResponse({"status": "error", "message": "No client_id provided"}, status_code=400)

    if keyword in state.watch_registry and client_id in state.watch_registry[keyword]:
        state.watch_registry[keyword].remove(client_id)
        if not state.watch_registry[keyword]:
            del state.watch_registry[keyword]
        logger.info("Unregistered keyword watch", extra={"client_id": client_id, "keyword": keyword})

    return {"status": "success"}


@router.post("/sync-watch")
async def sync_watch(request: Request, data: SyncWatchRequest):
    auth_check = await require_auth(request)
    if auth_check:
        return auth_check

    for keyword in list(state.watch_registry.keys()):
        if data.client_id in state.watch_registry[keyword]:
            state.watch_registry[keyword].remove(data.client_id)
            if not state.watch_registry[keyword]:
                del state.watch_registry[keyword]

    for keyword in data.keywords:
        state.watch_registry.setdefault(keyword, set()).add(data.client_id)

    logger.info(
        "Synchronized keyword watches",
        extra={"client_id": data.client_id, "keyword_count": len(data.keywords)},
    )
    return {"status": "success", "count": len(data.keywords)}
