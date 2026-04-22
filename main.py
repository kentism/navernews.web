import asyncio
import re
from typing import List

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import BaseModel
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app_config import (
    APP_ACCESS_KEY,
    DEFAULT_KEYWORDS,
    MAX_NOTIFICATION_HISTORY,
    NOTIFICATION_HISTORY_TTL_SECONDS,
    POLLING_INTERVAL,
    STATIC_DIR,
    TEMPLATES_DIR,
    WATCHER_STALE_SECONDS,
)
from app_logging import configure_logging, get_logger
from services.monitoring import state
from services.news_service import NewsItem, fetch_news, get_naver_api_headers, parse_article
from utils.template_filters import extract_highlight_keyword, time_ago


configure_logging()
logger = get_logger("main")

app = FastAPI()
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


async def verify_access(request: Request):
    if request.url.path in ["/login", "/static/css/style.css"]:
        return None

    access_token = request.cookies.get("access_token")
    if access_token != APP_ACCESS_KEY:
        return RedirectResponse(url="/login", status_code=303)

    return None


def highlight_keyword(text, keyword):
    try:
        if not keyword or not text:
            return text

        cleaned_keyword = extract_highlight_keyword(keyword)
        if not cleaned_keyword:
            return text

        pattern = re.compile(re.escape(cleaned_keyword), re.IGNORECASE)
        highlighted = pattern.sub(
            lambda match: f'<mark class="highlight">{match.group(0)}</mark>',
            text,
        )
        return Markup(highlighted)
    except Exception as exc:
        logger.warning("highlight filter failed", extra={"error": str(exc)})
        return text


templates.env.filters["time_ago"] = time_ago
templates.env.filters["highlight"] = highlight_keyword


def _current_loop_time() -> float:
    return asyncio.get_running_loop().time()


def _prune_notification_history(now: float) -> None:
    state.notification_history[:] = [
        entry
        for entry in state.notification_history
        if (now - entry[0]) < NOTIFICATION_HISTORY_TTL_SECONDS
    ]


async def poll_naver_news_task():
    logger.info("Starting polling task", extra={"interval_seconds": POLLING_INTERVAL})

    while True:
        try:
            active_keywords = list(state.watch_registry.keys())
            if not active_keywords:
                await asyncio.sleep(POLLING_INTERVAL)
                continue

            headers = await get_naver_api_headers()
            if not headers.get("X-Naver-Client-Id"):
                await asyncio.sleep(POLLING_INTERVAL)
                continue

            now = _current_loop_time()
            _prune_notification_history(now)

            for keyword in active_keywords:
                watcher_ids = state.watch_registry.get(keyword, set())
                online_watchers = [cid for cid in watcher_ids if cid in state.sse_connections]

                if not online_watchers:
                    all_stale = all(
                        (now - state.last_seen_clients.get(cid, 0)) >= WATCHER_STALE_SECONDS
                        for cid in watcher_ids
                    )
                    if all_stale:
                        state.watch_registry.pop(keyword, None)
                        logger.info("Pruned stale keyword watcher", extra={"keyword": keyword})
                    continue

                items = await fetch_news(keyword, headers=headers, start=1, display=20)
                if not items:
                    continue

                latest_link = items[0].link
                cache_key = f"{keyword}_1"
                cached_items = state.search_cache.get(cache_key, [])
                is_new = bool(cached_items) and latest_link != cached_items[0].link

                state.search_cache[cache_key] = items

                if not is_new:
                    continue

                message = f"[{keyword}] 관련 새로운 기사가 감지되었습니다."
                state.notification_history.append((now, keyword, message))
                if len(state.notification_history) > MAX_NOTIFICATION_HISTORY:
                    state.notification_history.pop(0)

                logger.info("Detected new article", extra={"keyword": keyword, "latest_link": latest_link})
                for client_id in list(watcher_ids):
                    queue = state.sse_connections.get(client_id)
                    if queue:
                        await queue.put(message)

        except Exception as exc:
            logger.exception("Polling loop failed", extra={"error": str(exc)})

        await asyncio.sleep(POLLING_INTERVAL)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(poll_naver_news_task())


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "Unhandled application error",
        extra={"path": request.url.path, "method": request.method, "error": str(exc)},
    )

    if request.url.path.startswith("/api/"):
        return JSONResponse(
            content={"error": "서버 내부 오류가 발생했습니다. 잠시 후 다시 시도해주세요."},
            status_code=500,
        )

    return HTMLResponse(
        content="<h2>서버 오류가 발생했습니다.</h2><p>잠시 후 다시 시도해주세요.</p>",
        status_code=500,
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None):
    return templates.TemplateResponse(request=request, name="login.html", context={"error": error})


@app.post("/login")
async def login(password: str = Form(...)):
    if password == APP_ACCESS_KEY:
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key="access_token",
            value=APP_ACCESS_KEY,
            httponly=True,
            samesite="lax",
        )
        return response

    return RedirectResponse(url="/login?error=Invalid+Password", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    auth_check = await verify_access(request)
    if auth_check:
        return auth_check

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "default_keywords": DEFAULT_KEYWORDS,
            "storage_notice": "클리핑 메모, 최근 검색어, 알림 상태는 현재 사용 중인 브라우저에 저장됩니다.",
        },
    )


@app.post("/api/search", response_class=JSONResponse)
async def search_api(
    request: Request,
    keyword: str = Form(...),
    start: int = Form(default=1),
    headers: dict = Depends(get_naver_api_headers),
):
    auth_check = await verify_access(request)
    if auth_check:
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    cache_key = f"{keyword}_{start}"
    items = state.search_cache.get(cache_key)
    if items is None:
        items = await fetch_news(keyword, headers=headers, start=start, display=20)
        if start == 1:
            state.search_cache[cache_key] = items

    return {"items": [item.model_dump() for item in items], "total": len(items)}


@app.post("/search-results", response_class=HTMLResponse)
async def search_results(
    request: Request,
    keyword: str = Form(...),
    start: int = Form(default=1),
    headers: dict = Depends(get_naver_api_headers),
):
    auth_check = await verify_access(request)
    if auth_check:
        return auth_check

    cache_key = f"{keyword}_{start}"
    form = await request.form()
    is_refresh = form.get("refresh") == "true"

    items = state.search_cache.get(cache_key)
    if items is None or is_refresh:
        items = await fetch_news(keyword, headers=headers, start=start, display=20)
        if start == 1:
            state.search_cache[cache_key] = items

    return templates.TemplateResponse(
        request=request,
        name="search_results.html",
        context={"items": items, "keyword": keyword, "start": start + 20},
    )


@app.get("/api/article", response_class=JSONResponse)
async def get_article_content(url: str):
    content = await parse_article(url)
    return {"content": content}


@app.get("/clippings-tab", response_class=HTMLResponse)
async def clippings_tab(request: Request):
    auth_check = await verify_access(request)
    if auth_check:
        return auth_check

    return templates.TemplateResponse(
        request=request,
        name="clippings_tab.html",
        context={
            "storage_notice": "이 탭의 메모와 알림 설정은 브라우저 로컬 저장소를 사용합니다.",
        },
    )


@app.get("/alerts-tab", response_class=HTMLResponse)
async def alerts_tab(request: Request):
    auth_check = await verify_access(request)
    if auth_check:
        return auth_check

    return templates.TemplateResponse(
        request=request,
        name="alerts_tab.html",
        context={
            "storage_notice": "알림 상태는 현재 브라우저 로컬 저장소와 실시간 연결 상태를 기준으로 동작합니다.",
        },
    )


@app.get("/api/stream/notifications")
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
                    yield ": ping\n\n"
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


@app.post("/api/watch")
async def watch_keyword(request: Request, keyword: str = Form(...), client_id: str = Form(None)):
    auth_check = await verify_access(request)
    if auth_check:
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    if not client_id:
        return JSONResponse({"status": "error", "message": "No client_id provided"}, status_code=400)

    state.watch_registry.setdefault(keyword, set()).add(client_id)
    logger.info("Registered keyword watch", extra={"client_id": client_id, "keyword": keyword})
    return {"status": "success", "keyword": keyword}


@app.post("/api/unwatch")
async def unwatch_keyword(request: Request, keyword: str = Form(...), client_id: str = Form(None)):
    auth_check = await verify_access(request)
    if auth_check:
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    if client_id and keyword in state.watch_registry:
        state.watch_registry[keyword].discard(client_id)
        if not state.watch_registry[keyword]:
            del state.watch_registry[keyword]
        logger.info("Unregistered keyword watch", extra={"client_id": client_id, "keyword": keyword})

    return {"status": "success"}


class SyncWatchRequest(BaseModel):
    client_id: str
    keywords: List[str]


@app.post("/api/sync-watch")
async def sync_watch(request: Request, data: SyncWatchRequest):
    auth_check = await verify_access(request)
    if auth_check:
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

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
