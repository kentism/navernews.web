from urllib.parse import urlsplit

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from routers.auth import require_auth
from services.article_title_confirmation import TitleConfirmationService, verify_confirmation

router = APIRouter()


@router.post('/api/search/title-confirmation')
async def confirm_title(request: Request, token: str = Form(..., min_length=1, max_length=8192)):
    auth = await require_auth(request)
    if auth:
        return auth
    origin = request.headers.get('origin')
    if origin:
        try:
            source, target = urlsplit(origin), urlsplit(str(request.base_url))
            allowed = (source.scheme, source.netloc) == (target.scheme, target.netloc)
        except ValueError:
            allowed = False
        if not allowed:
            return JSONResponse({'error': '허용되지 않은 요청입니다.'}, status_code=403)
    try:
        sample = verify_confirmation(token)
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)
    service = getattr(request.app.state, 'title_confirmation', None)
    if service is None:
        service = TitleConfirmationService()
        request.app.state.title_confirmation = service
    result = await service.confirm(sample)
    return JSONResponse(result, headers={'Cache-Control': 'no-store'})
