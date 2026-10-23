from fastapi import APIRouter, Request

from app_config import DEFAULT_KEYWORDS
from routers.auth import require_auth

router = APIRouter()


async def render_page(request, name, **context):
    auth = await require_auth(request)
    if auth:
        return auth
    return request.app.state.templates.TemplateResponse(request=request, name=name, context=context)


@router.get("/")
async def home(request: Request):
    return await render_page(
        request, "index.html", default_keywords=DEFAULT_KEYWORDS,
        storage_notice="작성 중인 클리핑은 현재 브라우저에 저장됩니다. 완성본은 파일로 보관할 수 있습니다.")


@router.get("/clippings-tab")
async def clippings_tab(request: Request):
    return await render_page(request, "clippings_tab.html",
                             storage_notice="알림 설정은 현재 브라우저에 저장됩니다.")


@router.get("/alerts-tab")
async def alerts_tab(request: Request):
    return await render_page(request, "alerts_tab.html",
                             storage_notice="알림 설정은 현재 브라우저에 저장됩니다.")
