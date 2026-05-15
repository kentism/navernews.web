from fastapi import Request


async def require_auth(request: Request):
    verify_access = request.app.state.verify_access
    auth_check = await verify_access(request)
    return auth_check if auth_check else None
