import re
import asyncio

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
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
from services.clipping_store import (
    DEFAULT_CATEGORIES,
    get_storage_status,
    init_db,
)
from services.monitoring import state
from services.news_service import fetch_news, get_naver_api_headers
from routers.candidates import router as candidates_router
from routers.clippings import router as clippings_router
from routers.notifications import router as notifications_router
from routers.search import router as search_router
from routers.storage import router as storage_router
from utils.template_filters import extract_highlight_keyword, time_ago


configure_logging()
logger = get_logger("main")

app = FastAPI()
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.state.templates = templates


async def verify_access(request: Request):
    if request.url.path in ["/login", "/static/css/style.css"]:
        return None

    access_token = request.cookies.get("access_token")
    if access_token != APP_ACCESS_KEY:
        if request.url.path.startswith("/api/"):
            return JSONResponse(content={"error": "Unauthorized"}, status_code=401)
        return RedirectResponse(url="/login", status_code=303)

    return None


app.state.verify_access = verify_access
app.include_router(candidates_router)
app.include_router(clippings_router)
app.include_router(notifications_router)
app.include_router(search_router)
app.include_router(storage_router)


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

                message = f"[{keyword}] 愿???덈줈??湲곗궗媛 媛먯??섏뿀?듬땲??"
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
    init_db()
    storage_status = get_storage_status()
    logger.info(
        "Initialized clipping storage",
        extra={
            "db_path": storage_status["db_path"],
            "data_dir_writable": storage_status["data_dir_writable"],
            "db_size_bytes": storage_status["db_size_bytes"],
        },
    )
    asyncio.create_task(poll_naver_news_task())


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "Unhandled application error",
        extra={"path": request.url.path, "method": request.method, "error": str(exc)},
    )

    if request.url.path.startswith("/api/"):
        return JSONResponse(
            content={"error": "?쒕쾭 ?대? ?ㅻ쪟媛 諛쒖깮?덉뒿?덈떎. ?좎떆 ???ㅼ떆 ?쒕룄?댁＜?몄슂."},
            status_code=500,
        )

    return HTMLResponse(
        content="<h2>?쒕쾭 ?ㅻ쪟媛 諛쒖깮?덉뒿?덈떎.</h2><p>?좎떆 ???ㅼ떆 ?쒕룄?댁＜?몄슂.</p>",
        status_code=500,
    )


@app.get("/healthz", response_class=JSONResponse)
async def healthz():
    return {"status": "ok"}


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
            "storage_notice": "?대━??硫붾え, 理쒓렐 寃?됱뼱, ?뚮┝ ?곹깭???꾩옱 ?ъ슜 以묒씤 釉뚮씪?곗?????λ맗?덈떎.",
        },
    )


@app.get("/clippings-tab", response_class=HTMLResponse)
async def clippings_tab(request: Request):
    auth_check = await verify_access(request)
    if auth_check:
        return auth_check

    return templates.TemplateResponse(
        request=request,
        name="clippings_tab.html",
        context={
            "storage_notice": "????쓽 硫붾え? ?뚮┝ ?ㅼ젙? 釉뚮씪?곗? 濡쒖뺄 ??μ냼瑜??ъ슜?⑸땲??",
        },
    )


@app.get("/candidates-tab", response_class=HTMLResponse)
async def candidates_tab(request: Request):
    auth_check = await verify_access(request)
    if auth_check:
        return auth_check

    return templates.TemplateResponse(
        request=request,
        name="candidates_tab.html",
        context={"categories": DEFAULT_CATEGORIES},
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
            "storage_notice": "?뚮┝ ?곹깭???꾩옱 釉뚮씪?곗? 濡쒖뺄 ??μ냼? ?ㅼ떆媛??곌껐 ?곹깭瑜?湲곗??쇰줈 ?숈옉?⑸땲??",
        },
    )



