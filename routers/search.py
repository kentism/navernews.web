from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from routers.auth import require_auth
from services.monitoring import state
from services.news_service import fetch_news, get_naver_api_headers, parse_article


router = APIRouter()


@router.post("/api/search", response_class=JSONResponse)
async def search_api(
    request: Request,
    keyword: str = Form(...),
    start: int = Form(default=1),
    headers: dict = Depends(get_naver_api_headers),
):
    auth_check = await require_auth(request)
    if auth_check:
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    cache_key = f"{keyword}_{start}"
    items = state.search_cache.get(cache_key)
    if items is None:
        items = await fetch_news(keyword, headers=headers, start=start, display=20)
        if start == 1:
            state.search_cache[cache_key] = items

    return {"items": [item.model_dump() for item in items], "total": len(items)}


@router.post("/search-results", response_class=HTMLResponse)
async def search_results(
    request: Request,
    keyword: str = Form(...),
    start: int = Form(default=1),
    headers: dict = Depends(get_naver_api_headers),
):
    auth_check = await require_auth(request)
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

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="search_results.html",
        context={"items": items, "keyword": keyword, "start": start + 20},
    )


@router.get("/api/article", response_class=JSONResponse)
async def get_article_content(url: str):
    content = await parse_article(url)
    return {"content": content}
