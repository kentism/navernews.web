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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from bs4 import BeautifulSoup
from pydantic import BaseModel
from markupsafe import Markup
import asyncio

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

# ==============================================================================
# 3. CACHING & BACKGROUND POLLING (SSE)
# ==============================================================================

# In-Memory Cache for searches
SEARCH_CACHE = {}

# Registry for dynamic keyword watching: { "keyword": set(connection_ids) }
WATCH_REGISTRY = {}
# Connection to Queue mapping: { connection_id: asyncio.Queue }
sse_connections = {}

POLLING_INTERVAL = 60 # 1 minute

async def poll_naver_news_task():
    """Background task to poll keywords that have active watchers."""
    print(f"[Polling] Started dynamic background polling task every {POLLING_INTERVAL}s")
    while True:
        try:
            active_keywords = list(WATCH_REGISTRY.keys())
            if not active_keywords:
                await asyncio.sleep(POLLING_INTERVAL)
                continue
            
            headers = await get_naver_api_headers()
            if not headers.get("X-Naver-Client-Id"):
                await asyncio.sleep(POLLING_INTERVAL)
                continue

            for keyword in active_keywords:
                # Consolidate: Fetch 20 items once
                items = await fetch_news(keyword, headers=headers, start=1, display=20)
                
                if items:
                    latest_link = items[0].link
                    cache_key = f"{keyword}_1"
                    cached_data = SEARCH_CACHE.get(cache_key)
                    
                    is_new = False
                    if cached_data and len(cached_data) > 0:
                        if latest_link != cached_data[0].link:
                            is_new = True
                    
                    # Update Cache
                    SEARCH_CACHE[cache_key] = items
                    
                    if is_new:
                        print(f"[Polling] New article detected for: {keyword}")
                        message = f"[{keyword}] 관련 새로운 기사가 감지되었습니다."
                        
                        # Notify only the clients watching THIS keyword
                        watcher_ids = WATCH_REGISTRY.get(keyword, set())
                        for conn_id in list(watcher_ids):
                            q = sse_connections.get(conn_id)
                            if q:
                                await q.put(message)
                        
        except Exception as e:
            print(f"[Polling Error] {e}")
            
        await asyncio.sleep(POLLING_INTERVAL)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(poll_naver_news_task())

# ==============================================================================
# 5. ROUTERS (ENDPOINTS)
# ==============================================================================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None):
    """Renders the login page."""
    return templates.TemplateResponse(request=request, name="login.html", context={"error": error})

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
    return templates.TemplateResponse(request=request, name="index.html")

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
    
    # Simple explicit string matching to bypass complicated parsing
    cache_key = f"{keyword}_{start}"
    if cache_key in SEARCH_CACHE:
        items = SEARCH_CACHE[cache_key]
    else:
        items = await fetch_news(keyword, headers=headers, start=start, display=20)
        # Store in cache only for the first page
        if start == 1:
            SEARCH_CACHE[cache_key] = items
            
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
        cache_key = f"{keyword}_{start}"
        is_refresh = (await request.form()).get("refresh") == "true"
        
        if cache_key in SEARCH_CACHE and not is_refresh:
            items = SEARCH_CACHE[cache_key]
        else:
            items = await fetch_news(keyword, headers=headers, start=start, display=20)
            if start == 1:
                SEARCH_CACHE[cache_key] = items

        return templates.TemplateResponse(request=request, name="search_results.html", context={
            "items": items, "keyword": keyword, "start": start + 20
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
    return templates.TemplateResponse(request=request, name="clippings_tab.html")

@app.get("/api/stream/notifications")
async def sse_notifications(request: Request):
    """Server-Sent Events endpoint for real-time notifications."""
    conn_id = str(id(request))
    async def event_generator():
        yield f"data: conn_id:{conn_id}\n\n"
        q = asyncio.Queue()
        sse_connections[conn_id] = q
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await q.get()
                yield f"data: {message}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            # Clean up connection
            if conn_id in sse_connections:
                del sse_connections[conn_id]
            # Clean up all watches for this connection
            for kw in list(WATCH_REGISTRY.keys()):
                if conn_id in WATCH_REGISTRY[kw]:
                    WATCH_REGISTRY[kw].remove(conn_id)
                    if not WATCH_REGISTRY[kw]:
                        del WATCH_REGISTRY[kw]
                        
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/watch")
async def watch_keyword(request: Request, keyword: str = Form(...), conn_id: str = Form(None)):
    """Registers a keyword for polling by a specific connection."""
    if not conn_id or conn_id not in sse_connections:
        # If no client ID provided or found, we can't tie it to a listener
        return JSONResponse({"status": "error", "message": "No active SSE connection found"}, status_code=400)
    
    if keyword not in WATCH_REGISTRY:
        WATCH_REGISTRY[keyword] = set()
    WATCH_REGISTRY[keyword].add(conn_id)
    print(f"[Watch] Client {conn_id} started watching: {keyword}")
    return {"status": "success", "keyword": keyword}

@app.post("/api/unwatch")
async def unwatch_keyword(request: Request, keyword: str = Form(...), conn_id: str = Form(None)):
    """Unregisters a keyword."""
    if conn_id and keyword in WATCH_REGISTRY:
        if conn_id in WATCH_REGISTRY[keyword]:
            WATCH_REGISTRY[keyword].remove(conn_id)
            if not WATCH_REGISTRY[keyword]:
                del WATCH_REGISTRY[keyword]
            print(f"[Unwatch] Client {conn_id} stopped watching: {keyword}")
    return {"status": "success"}
