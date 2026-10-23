from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse

from routers.auth import require_auth
from services.monitoring import cache_search_results
from services.news_service import NEWS_API_LIMIT, NewsServiceError, fetch_news_page, get_naver_api_headers
from services.search_collection import collect_articles

router = APIRouter()


@router.post("/api/search")
async def search_api(request: Request, keyword: str = Form(..., min_length=1, max_length=300),
                     start: int = Form(1, ge=1, le=NEWS_API_LIMIT),
                     headers: dict = Depends(get_naver_api_headers)):
    auth = await require_auth(request)
    if auth:
        return auth
    try:
        page = await fetch_news_page(keyword, headers, start=start)
    except NewsServiceError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    return {"items": [item.model_dump() for item in page.items], "total": page.total,
            "next_start": page.next_start, "has_more": page.has_more}


@router.post("/search-results")
async def search_results(request: Request, keyword: str = Form(..., min_length=1, max_length=300),
                         start: int = Form(1, ge=1, le=NEWS_API_LIMIT),
                         headers: dict = Depends(get_naver_api_headers)):
    auth = await require_auth(request)
    if auth:
        return auth
    try:
        page = await fetch_news_page(keyword, headers, start=start)
    except NewsServiceError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    if start == 1:
        cache_search_results(keyword, page.items)
    return request.app.state.templates.TemplateResponse(
        request=request, name="search_results.html",
        context={"items": page.items, "keyword": keyword, "page": page, "mode": "latest"})


@router.post("/api/search/collect")
async def collect_search_results(request: Request, keyword: str = Form(..., min_length=1, max_length=300),
                                 since: str = Form(...), until: str = Form(""),
                                 headers: dict = Depends(get_naver_api_headers)):
    auth = await require_auth(request)
    if auth:
        return auth
    try:
        result = await collect_articles(keyword, headers, since, until)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except NewsServiceError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    html = request.app.state.templates.get_template("search_results.html").render(
        items=result.items, keyword=keyword, mode="period", since=since, until=until)
    return {"html": html, "article_count": len(result.items), "checked_count": result.checked_count,
            "complete": result.complete, "limit_reached": result.limit_reached,
            "duplicate_count": result.duplicate_count, "invalid_date_count": result.invalid_date_count}
