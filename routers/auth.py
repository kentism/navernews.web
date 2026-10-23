from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app_config import APP_ACCESS_KEY

router = APIRouter()


async def require_auth(request: Request):
    if request.cookies.get("access_token") == APP_ACCESS_KEY:
        return None
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "인증이 만료되었습니다. 다시 로그인해주세요."}, status_code=401)
    return RedirectResponse("/login", status_code=303)


@router.get("/login")
async def login_page(request: Request, error: str = ""):
    return request.app.state.templates.TemplateResponse(
        request=request, name="login.html", context={"error": error})


@router.post("/login")
async def login(request: Request, password: str = Form(..., max_length=256)):
    if password != APP_ACCESS_KEY:
        return RedirectResponse("/login?error=Invalid+Password", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("access_token", APP_ACCESS_KEY, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")
    return response
