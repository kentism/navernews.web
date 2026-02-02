import httpx
import html
import os
import re
import uuid
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from datetime import datetime, timezone 
from typing import List
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime

from fastapi import FastAPI, Request, Form, Depends, HTTPException, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from bs4 import BeautifulSoup
from pydantic import BaseModel
from markupsafe import Markup

# ==============================================================================
# 1. CONFIGURATION & SETUP!
# ==============================================================================

# -- Path Configuration --
# Resolve absolute paths to prevent errors in various deployment environments (e.g., Railway).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(BASE_DIR, "static")
templates_dir = os.path.join(BASE_DIR, "templates")

# Verify essential directories exist
if not os.path.exists(static_dir):
    print(f"WARNING: Static directory not found at {static_dir}")

# -- App Initialization --
app = FastAPI()
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# -- Mount Static & Templates --
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

# -- Access Configuration --
# Shared password for the service. Ideally set via environment variable.
APP_ACCESS_KEY = os.getenv("APP_ACCESS_KEY", "32195114")

async def verify_access(request: Request):
    """Dependency to check if the user has the correct access token in cookies."""
    if request.url.path in ["/login", "/static/css/style.css"]:
        return
        
    access_token = request.cookies.get("access_token")
    if access_token != APP_ACCESS_KEY:
        return RedirectResponse(url="/login", status_code=303)


# ==============================================================================
# 2. TEMPLATE FILTERS
# ==============================================================================

def time_ago(value):
    """
    Converts a datetime object or string into a 'human-readable' time difference.
    e.g., 'Just now', '5 minutes ago', '2 hours ago'.
    """
    try:
        if not value:
            return ""
        
        # Handle string input (Naver API format)
        if isinstance(value, str):
            try:
                dt = parsedate_to_datetime(value)
            except:
                return value
        elif isinstance(value, datetime):
            dt = value
        else:
            return value

        if dt.tzinfo:
            now = datetime.now(timezone.utc)
        else:
            now = datetime.now()

        diff = now - dt
        seconds = diff.total_seconds()

        if seconds < 60:
            return "방금 전"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes}분 전"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}시간 전"
        elif seconds < 604800: # 7 days
            days = int(seconds / 86400)
            return f"{days}일 전"
        else:
            return dt.strftime("%Y-%m-%d")
    except Exception as e:
        print(f"[Filter Error] time_ago: {e}")
        return value

def highlight_keyword(text, keyword):
    """
    Wraps occurrences of 'keyword' in the text with <mark> tags for highlighting.
    Case-insensitive.
    """
    try:
        if not keyword or not text:
            return text
        
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        
        def replace_func(match):
            return f'<mark class="highlight">{match.group(0)}</mark>'
        
        highlighted = pattern.sub(replace_func, text)
        return Markup(highlighted)
    except Exception as e:
        print(f"[Filter Error] highlight_keyword: {e}")
        return text

# Register filters
templates.env.filters["time_ago"] = time_ago
templates.env.filters["highlight"] = highlight_keyword


# -- Scraper Logic Import --
from scraper import NewsItem, fetch_news, parse_article, get_naver_api_headers

# -- In-Memory Cache (Legacy) --
SEARCH_CACHE = {}


# ==============================================================================
# 5. ROUTERS (ENDPOINTS)
# ==============================================================================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None):
    """Renders the login page."""
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@app.post("/login")
async def login(password: str = Form(...)):
    """Handles login form submission."""
    if password == APP_ACCESS_KEY:
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(key="access_token", value=APP_ACCESS_KEY, httponly=True)
        return response
    return RedirectResponse(url="/login?error=Invalid+Password", status_code=303)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Renders the main homepage."""
    # Check access (re-using the logic as a manual check if not using Depends globally)
    auth_check = await verify_access(request)
    if auth_check: return auth_check
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/search", response_class=JSONResponse)
async def search_api(
    request: Request,
    keyword: str = Form(...), 
    start: int = Form(default=1), 
    headers: dict = Depends(get_naver_api_headers)
):
    """API endpoint for JSON search results."""
    auth_check = await verify_access(request)
    if auth_check: return JSONResponse(content={"error": "Unauthorized"}, status_code=401)
    
    items = await fetch_news(keyword, headers=headers, start=start, display=20)
    return {"items": [item.dict() for item in items], "total": len(items)}

@app.post("/search-results", response_class=HTMLResponse)
async def search_results(
    request: Request, 
    keyword: str = Form(...), 
    start: int = Form(default=1), 
    headers: dict = Depends(get_naver_api_headers)
):
    """Renders search results page (Server-Side Rendering)."""
    auth_check = await verify_access(request)
    if auth_check: return auth_check
    
    try:
        items = await fetch_news(keyword, headers=headers, start=start, display=20)
        return templates.TemplateResponse("search_results.html", {
            "request": request, "items": items, "keyword": keyword, "start": start + 20
        })
    except Exception as e:
        import traceback
        error_msg = f"Server Error: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        return HTMLResponse(content=f"<pre>{error_msg}</pre>", status_code=500)

@app.get("/api/article", response_class=JSONResponse)
async def get_article_content(url: str):
    """API endpoint to fetch article content (for async loading if needed)."""
    content = await parse_article(url)
    return {"content": content}

@app.get("/clippings-tab", response_class=HTMLResponse)
async def clippings_tab(request: Request):
    """Renders the clippings (saved news) tab."""
    auth_check = await verify_access(request)
    if auth_check: return auth_check
    return templates.TemplateResponse("clippings_tab.html", {"request": request})
