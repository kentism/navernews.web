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

# Registry for dynamic keyword watching: { "keyword": set(client_ids) }
WATCH_REGISTRY = {}
# Connection to Queue mapping: { client_id: asyncio.Queue }
sse_connections = {}
# Last activity timestamp per client: { client_id: float_timestamp }
LAST_SEEN_CLIENTS = {}
# Recent notification buffer: [ (timestamp, keyword, message) ]
NOTIFICATION_HISTORY = []

POLLING_INTERVAL = 30 # 30 seconds

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
                # 🛡️ Pruning Logic: Only poll if there's at least one online watcher
                watcher_ids = WATCH_REGISTRY.get(keyword, set())
                online_watchers = [cid for cid in watcher_ids if cid in sse_connections]
                
                if not online_watchers:
                    # 🕒 Grace Period: Check if all watchers have been inactive for > 120s
                    all_stale = True
                    for cid in watcher_ids:
                        last_seen = LAST_SEEN_CLIENTS.get(cid, 0)
                        if (asyncio.get_event_loop().time() - last_seen) < 120:
                            all_stale = False
                            break
                    
                    if all_stale:
                        print(f"[Polling] Pruning keyword with no active watchers for 120s: {keyword}")
                        if keyword in WATCH_REGISTRY:
                            del WATCH_REGISTRY[keyword]
                    continue

                # Fetch news only if we have active, potentially offline-reconnecting watchers
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
                        current_time = asyncio.get_event_loop().time()
                        print(f"[Polling] New article detected for: {keyword}")
                        message = f"[{keyword}] 관련 새로운 기사가 감지되었습니다."
                        
                        # Store in history buffer (keep last 50)
                        NOTIFICATION_HISTORY.append((current_time, keyword, message))
                        if len(NOTIFICATION_HISTORY) > 50:
                            NOTIFICATION_HISTORY.pop(0)
                        
                        # Notify only the clients watching THIS keyword
                        for client_id in list(watcher_ids):
                            q = sse_connections.get(client_id)
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
async def sse_notifications(request: Request, client_id: str = None):
    """Server-Sent Events endpoint for real-time notifications."""
    if not client_id:
        return JSONResponse(content={"error": "client_id is required"}, status_code=400)
        
    async def event_generator():
        # Update last seen
        current_time = asyncio.get_event_loop().time()
        LAST_SEEN_CLIENTS[client_id] = current_time
        
        # Clean up any existing connection
        if client_id in sse_connections:
            pass
            
        q = asyncio.Queue()
        sse_connections[client_id] = q
        
        try:
            # Send initial confirmation
            yield f"data: connected:{client_id}\n\n"
            
            # 🚀 Catch-up: Replay missed notifications for this client's keywords
            # Check notifications from the last 2 minutes
            client_keywords = []
            for kw, watchers in WATCH_REGISTRY.items():
                if client_id in watchers:
                    client_keywords.append(kw)
            
            if client_keywords:
                for ts, kw, msg in NOTIFICATION_HISTORY:
                    if kw in client_keywords and (current_time - ts) < 120:
                        yield f"data: {msg}\n\n"
            
            while True:
                if await request.is_disconnected():
                    break
                
                try:
                    message = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {message}\n\n"
                    # Update last seen on activity
                    LAST_SEEN_CLIENTS[client_id] = asyncio.get_event_loop().time()
                except asyncio.TimeoutError:
                    # Heartbeat
                    yield ": ping\n\n"
                    LAST_SEEN_CLIENTS[client_id] = asyncio.get_event_loop().time()
        except asyncio.CancelledError:
            pass
        finally:
            if client_id in sse_connections:
                del sse_connections[client_id]
            # Pruning is handled by the background task grace period now
            LAST_SEEN_CLIENTS[client_id] = asyncio.get_event_loop().time()
                        
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/watch")
async def watch_keyword(request: Request, keyword: str = Form(...), client_id: str = Form(None)):
    """Registers a keyword for polling by a specific client."""
    if not client_id:
        return JSONResponse({"status": "error", "message": "No client_id provided"}, status_code=400)
    
    # We allow watching even if SSE is temporarily disconnected, 
    # as long as we have the client_id
    if keyword not in WATCH_REGISTRY:
        WATCH_REGISTRY[keyword] = set()
    WATCH_REGISTRY[keyword].add(client_id)
    print(f"[Watch] Client {client_id} started watching: {keyword}")
    return {"status": "success", "keyword": keyword}

@app.post("/api/unwatch")
async def unwatch_keyword(request: Request, keyword: str = Form(...), client_id: str = Form(None)):
    """Unregisters a keyword."""
    if client_id and keyword in WATCH_REGISTRY:
        if client_id in WATCH_REGISTRY[keyword]:
            WATCH_REGISTRY[keyword].remove(client_id)
            if not WATCH_REGISTRY[keyword]:
                del WATCH_REGISTRY[keyword]
            print(f"[Unwatch] Client {client_id} stopped watching: {keyword}")
    return {"status": "success"}

class SyncWatchRequest(BaseModel):
    client_id: str
    keywords: List[str]

@app.post("/api/sync-watch")
async def sync_watch(request: Request, data: SyncWatchRequest):
    """Absolutely synchronizes the watch list for a specific client."""
    client_id = data.client_id
    keywords = data.keywords
    
    # 1. Remove this client from all existing watches
    for kw in list(WATCH_REGISTRY.keys()):
        if client_id in WATCH_REGISTRY[kw]:
            WATCH_REGISTRY[kw].remove(client_id)
            if not WATCH_REGISTRY[kw]:
                del WATCH_REGISTRY[kw]
    
    # 2. Add the client back to ONLY the requested keywords
    for kw in keywords:
        if kw not in WATCH_REGISTRY:
            WATCH_REGISTRY[kw] = set()
        WATCH_REGISTRY[kw].add(client_id)
    
    print(f"[Sync] Client {client_id} synced {len(keywords)} keywords: {keywords}")
    return {"status": "success", "count": len(keywords)}
