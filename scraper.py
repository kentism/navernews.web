import httpx
import html
import re
import os
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup
from pydantic import BaseModel

from services.media_source_registry import MEDIA_DOMAIN_MAP, resolve_media_source

# -- Domain Mapping --
DOMAIN_MAP = MEDIA_DOMAIN_MAP

class NewsItem(BaseModel):
    title: str
    link: str
    description: str
    originallink: str = ""
    source: str = ""
    pubDate: str = ""
    domain: str = ""
    formatted_pubdate: str = ""

async def get_naver_api_headers():
    """Retrieves Naver API credentials from environment variables."""
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        print("[ALERT] Naver API keys are missing in environment variables.")
        
    return {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}

async def fetch_news(keyword: str, headers: dict, start: int = 1, display: int = 20):
    """
    Fetches news data from Naver Open API.
    Handles HTML unescaping, date formatting, and source mapping.
    """
    url = "https://openapi.naver.com/v1/search/news.json"
    params = {"query": keyword, "display": display, "start": start, "sort": "date"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()
    except Exception as e:
        print(f"[API Error] fetch_news: {e}")
        return []

    items = []
    for item in data.get("items", []):
        # Clean HTML tags from title/description
        raw_title = item.get("title", "")
        raw_desc = item.get("description", "")
        clean_title = html.unescape(re.sub(r"<[^>]*>", "", raw_title))
        clean_desc = html.unescape(re.sub(r"<[^>]*>", "", raw_desc))
        
        # Determine Source/Domain
        origin = item.get("originallink") or item.get("link") or ""
        resolution = resolve_media_source(origin, item.get("source", ""))
        domain = resolution.domain
        source = resolution.source

        # Format Date
        raw_pub = item.get("pubDate", "")
        formatted_pub = raw_pub
        if raw_pub:
            try:
                dt = parsedate_to_datetime(raw_pub)
                formatted_pub = f"{dt.year}년 {dt.month}월 {dt.day}일 {dt.hour}시 {dt.minute}분"
            except:
                pass
        
        items.append(NewsItem(
            title=clean_title, 
            link=item.get("link", ""), 
            description=clean_desc,
            originallink=item.get("originallink", ""), 
            source=source,
            pubDate=raw_pub, 
            domain=domain, 
            formatted_pubdate=formatted_pub
        ))

    # --- 🔍 Server-Side Strict Filtering (2nd layer) ---
    # Extract includes and excludes from keyword
    includes = re.findall(r'\+"([^"]+)"', keyword) + re.findall(r'\+([^\s"]+)', keyword)
    excludes = re.findall(r'-([^\s"]+)', keyword)
    
    if not includes and not excludes:
        return items
        
    filtered_items = []
    for item in items:
        # Check both title and description for matches
        search_text = (item.title + " " + item.description).lower()
        
        # 🟢 Must Include ALL
        all_included = True
        for inc in includes:
            if inc.lower() not in search_text:
                all_included = False
                break
        
        if not all_included:
            continue
            
        # 🔴 Must NOT include ANY
        contains_exclude = False
        for ex in excludes:
            if ex.lower() in search_text:
                contains_exclude = True
                break
        
        if contains_exclude:
            continue
            
        filtered_items.append(item)
        
    return filtered_items

async def parse_article(url: str) -> str:
    """
    Crawls the target URL to extract the main article content.
    Uses a heuristic approach with common class names/IDs.
    """
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(url)
            html_content = response.text
        
        soup = BeautifulSoup(html_content, "html.parser")
        
        # List of common selectors for article bodies in Korean news sites
        candidates = [
            {"tag": "div", "class": "article_body"},
            {"tag": "div", "class": "newsct_article"},
            {"tag": "div", "class": "go_trans"},
            {"tag": "article", "class": None},
            {"tag": "div", "class": "article"},
            {"tag": "div", "id": "articleBody"},
        ]
        
        for c in candidates:
            section = soup.find(c["tag"], class_=c["class"]) if c["class"] else soup.find(c["tag"])
            if section:
                text = section.get_text(" ", strip=True)
                if len(text) > 50: return text
        
        # Fallback: Open Graph description
        og_desc = soup.find("meta", property="og:description")
        if og_desc: return og_desc.get("content", "")
        
        # Final Fallback: Raw text dump (truncated)
        return soup.get_text(" ", strip=True)[:1000] + "..."
    except Exception as e:
        return f"Content extraction failed: {str(e)}"
