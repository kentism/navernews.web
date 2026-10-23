import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app_config import STATIC_DIR, TEMPLATES_DIR
from app_logging import configure_logging, get_logger
from routers.auth import router as auth_router
from routers.notifications import router as notifications_router
from routers.pages import router as pages_router
from routers.search import router as search_router
from routers.storage import router as storage_router
from services.monitoring import poll_naver_news_task
from utils.template_filters import highlight_keyword, time_ago

configure_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app):
    """Run notification polling independently of retired learning storage."""
    task = asyncio.create_task(poll_naver_news_task())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(lifespan=lifespan)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters.update(time_ago=time_ago, highlight=highlight_keyword)
app.state.templates = templates
for router in (auth_router, pages_router, search_router, notifications_router, storage_router):
    app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled application error", extra={"path": request.url.path})
    message = "서버 내부 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": message}, status_code=500)
    return HTMLResponse("<h2>서버 오류가 발생했습니다.</h2>", status_code=500)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "mode": "search_clipping"}
