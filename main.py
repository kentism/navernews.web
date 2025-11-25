import httpx
import html
import os
import re
import uuid
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from datetime import datetime
from typing import List
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from bs4 import BeautifulSoup
from pydantic import BaseModel

# ----------------------------
# 1. 경로 및 앱 설정 (여기가 핵심 수정)
# ----------------------------
# 현재 파일(main.py)의 절대 경로를 구합니다.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI()
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# static과 templates 폴더를 절대 경로로 연결합니다.
# Railway에서 경로 오류를 방지하는 안전한 방법입니다.
static_dir = os.path.join(BASE_DIR, "static")
templates_dir = os.path.join(BASE_DIR, "templates")

# 폴더가 실제로 있는지 확인 (디버깅용)
if not os.path.exists(static_dir):
    print(f"⚠️ 경고: Static 폴더를 찾을 수 없습니다: {static_dir}")
    # 배포 환경에서 폴더가 비어있으면 git에 안 올라갈 수 있으니 주의

app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

# ----------------------------
# Jinja2 Custom Filters
# ----------------------------
from markupsafe import Markup

def time_ago(value):
    """
    datetime 객체 또는 날짜 문자열을 받아 '방금 전', 'X분 전' 등으로 변환합니다.
    """
    try:
        if not value:
            return ""
        
        if isinstance(value, str):
            try:
                # 네이버 API 날짜 포맷: "Thu, 21 Nov 2024 11:50:00 +0900"
                dt = parsedate_to_datetime(value)
                # timezone info 제거 (단순 비교를 위해)
                if dt.tzinfo:
                    dt = dt.replace(tzinfo=None)
            except:
                return value
        elif isinstance(value, datetime):
            dt = value
        else:
            return value

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
        elif seconds < 604800: # 7일
            days = int(seconds / 86400)
            return f"{days}일 전"
        else:
            return dt.strftime("%Y-%m-%d")
    except Exception as e:
        print(f"time_ago filter error: {e}")
        return value

def highlight_keyword(text, keyword):
    """
    텍스트에서 키워드를 찾아 <mark> 태그로 감쌉니다.
    """
    try:
        if not keyword or not text:
            return text
        
        # HTML 태그가 포함되어 있을 수 있으므로 unescape 후 처리하거나 주의 필요
        # 여기서는 단순 텍스트라고 가정하고 처리
        
        # 대소문자 구분 없이 검색
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        
        def replace_func(match):
            return f'<mark class="highlight">{match.group(0)}</mark>'
        
        highlighted = pattern.sub(replace_func, text)
        return Markup(highlighted)
    except Exception as e:
        print(f"highlight_keyword filter error: {e}")
        return text

templates.env.filters["time_ago"] = time_ago
templates.env.filters["highlight"] = highlight_keyword

# ----------------------------
# 의존성 및 데이터
# ----------------------------
async def get_naver_api_headers():
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    # 로컬 테스트나 배포 시 환경변수가 없을 경우를 대비해 로그만 남기고 진행하거나 예외처리
    if not client_id or not client_secret:
        print("⚠️ 네이버 API 키가 설정되지 않았습니다.")
    return {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}

# 도메인 맵 (너무 길어서 일부 생략 가능하지만, 원본 유지)
DOMAIN_MAP = {
    "joongang.joins.com": "중앙일보", "hani.co.kr": "한겨레", "yna.co.kr": "연합뉴스",
    "chosun.com": "조선일보", "donga.com": "동아일보", "mediatoday.co.kr": "미디어오늘",
    "journalist.or.kr": "기자협회보", "hankookilbo.com": "한국일보", "mbn.mk.co.kr": "MBN",
    "newscj.com": "천지일보", "news.jtbc.co.kr": "JTBC", "mediaus.co.kr": "미디어스",
    "dailian.co.kr": "데일리안", "view.asiae.co.kr": "아시아경제", "newspim.com": "뉴스핌",
    "news1.kr": "뉴스1", "asiatoday.co.kr": "아시아경제", "news.tvchosun.com": "TV조선",
    "digitaltoday.co.kr": "디지털투데이", "biz.chosun.com": "조선비즈", "newsis.com": "뉴시스",
    "biz.heraldcorp.com": "헤럴드경제", "etoday.co.kr": "이투데이", "ichannela.com": "채널A",
    "news.kbs.co.kr": "KBS", "kukinews.com": "쿠키뉴스", "yonhapnewstv.co.kr": "연합뉴스TV",
    "segye.com": "세계일보", "munhwa.com": "문화일보", "joongang.co.kr": "중앙일보",
    "ytn.co.kr": "YTN", "seoul.co.kr": "서울신문", "sedaily.com": "서울경제",
    "fnnews.com": "파이낸셜뉴스", "news.tf.co.kr": "더팩트", "news.sbs.co.kr": "SBS",
    "etnews.com": "전자신문", "sisajournal-e.com": "시사저널e", "zdnet.co.kr": "지디넷코리아",
    "mk.co.kr": "매일경제", "biz.sbs.co.kr": "SBSBiz", "weekly.chosun.com": "주간조선",
    "kmib.co.kr": "국민일보", "mt.co.kr": "머니투데이", "khan.co.kr": "경향신문", "inews24.com": "아이뉴스24",
    "it.chosun.com": "IT조선", "edaily.co.kr": "이데일리", "newstapa.org": "뉴스타파", "busan.com": "부산일보",
    "hankyung.com": "한국경제", "dt.co.kr": "디지털타임스", "pdjournal.com": "PD저널", "sisajournal.com": "시사저널",
    "nownews.seoul.co.kr": "서울신문", "kado.net": "강원도민일보", "imaeil.com": "매일신문", "sports.khan.co.kr": "스포츠경향",
    "pressian.com": "프레시안", "imnews.imbc.com": "MBC", "nocutnews.co.kr": "노컷뉴스", "ddaily.co.kr": "디지털데일리",
    "news.naver.com": "네이버", "news.daum.net": "다음", "sports.chosun.com": "스포츠조선",
    "sports.seoul.co.kr": "스포츠서울", "sports.donga.com": "스포츠동아", "sports.kbs.co.kr": "KBS",
    "sports.sbs.co.kr": "SBS 스포츠", "sports.mk.co.kr": "매일경제 스포츠", "news.kmib.co.kr": "국민일보",
    "news.heraldcorp.com": "헤럴드경제", "news.khan.co.kr": "경향신문", "news.hankyung.com": "한국경제",
    "news.imaeil.com": "매일신문", "news.busan.com": "부산일보", "news.joins.com": "중앙일보",
    "news.mt.co.kr": "머니투데이", "news.edaily.co.kr": "이데일리", "news.unn.net": "한국대학신문",
    "news.kukinews.com": "쿠키뉴스", "news.ajunews.com": "아주경제", "news.wowtv.co.kr": "한국경제TV",
    "news.g-enews.com": "글로벌이코노믹", "news.mtn.co.kr": "머니투데이방송", "news.ebs.co.kr": "EBS",
    "news.mbc.co.kr": "MBC", "newstomato.com": "뉴스토마토", "naeil.com": "내일신문", "insight.co.kr": "인사이트",
    "radio.ytn.co.kr": "YTN", "thebell.co.kr": "더벨", "wowtv.co.kr": "한국경제TV", "daejoilbo.com": "대전일보",
    "kyeongin.com": "경인일보", "kyeonggi.com": "경기일보", "kyeongbuk.co.kr": "경북일보", "kyongnam.com": "경남신문",
    "jnilbo.com": "전북일보", "jnnews.co.kr": "전남일보", "newdaily.co.kr": "뉴데일리", "ohmynews.com": "오마이뉴스",
    "bloter.net": "블로터", "moneys.co.kr": "머니S", "daily.hankooki.com": "데일리한국", "mbn.co.kr": "MBN",
    "jibs.co.kr": "JIBS", "topstarnews.net": "톱스타뉴스", "kookje.co.kr": "국제신문"
}

# 메모리 저장소 (서버 재시작 시 초기화됨)
SEARCH_CACHE = {}

class NewsItem(BaseModel):
    title: str
    link: str
    description: str
    originallink: str = ""
    source: str = ""
    pubDate: str = ""
    domain: str = ""
    formatted_pubdate: str = ""

# ----------------------------
# 비즈니스 로직
# ----------------------------
async def fetch_news(keyword: str, headers: dict, start: int = 1, display: int = 20):
    url = "https://openapi.naver.com/v1/search/news.json"
    params = {"query": keyword, "display": display, "start": start, "sort": "date"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()
    except Exception as e:
        print(f"네이버 API 호출 오류: {e}")
        return []

    items = []
    for item in data.get("items", []):
        clean_title = html.unescape(re.sub(r"<[^>]*>", "", item.get("title", "")))
        clean_desc = html.unescape(re.sub(r"<[^>]*>", "", item.get("description", "")))
        origin = item.get("originallink") or item.get("link") or ""
        
        source = item.get("source", "")
        netloc = urlparse(origin).netloc or ""
        domain = netloc.replace("www.", "")
        
        # pubDate 처리
        raw_pub = item.get("pubDate", "")
        formatted_pub = raw_pub
        if raw_pub:
            try:
                dt = parsedate_to_datetime(raw_pub)
                formatted_pub = f"{dt.year}년 {dt.month}월 {dt.day}일 {dt.hour}시 {dt.minute}분"
            except:
                pass
        
        if not source:
            source = DOMAIN_MAP.get(domain, domain)

        items.append(NewsItem(
            title=clean_title, link=item.get("link", ""), description=clean_desc,
            originallink=item.get("originallink", ""), source=source,
            pubDate=raw_pub, domain=domain, formatted_pubdate=formatted_pub
        ))
    return items

async def parse_article(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(url)
            html_content = response.text
        
        soup = BeautifulSoup(html_content, "html.parser")
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
        
        og_desc = soup.find("meta", property="og:description")
        if og_desc: return og_desc.get("content", "")
        
        return soup.get_text(" ", strip=True)[:1000] + "..." # 너무 길면 자름
    except Exception as e:
        return f"본문 수집 실패: {str(e)}"

# ----------------------------
# 라우터 (Endpoints)
# ----------------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # 여기서 index.html을 렌더링할 때 request 객체가 필수입니다.
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/search", response_class=JSONResponse)
async def search_api(keyword: str = Form(...), start: int = Form(default=1), headers: dict = Depends(get_naver_api_headers)):
    items = await fetch_news(keyword, headers=headers, start=start, display=20)
    return {"items": [item.dict() for item in items], "total": len(items)}

@app.post("/search-results", response_class=HTMLResponse)
async def search_results(request: Request, keyword: str = Form(...), start: int = Form(default=1), headers: dict = Depends(get_naver_api_headers)):
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
    try:
        content = await parse_article(url)
        return {"success": True, "content": content}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e), "content": ""}
        )

@app.post("/article-detail", response_class=HTMLResponse)
async def article_detail(request: Request, url: str = Form(...), title: str = Form(...)):
    content = await parse_article(url)
    return templates.TemplateResponse("article_detail.html", {
        "request": request, "title": title, "url": url, "content": content,
    })

@app.post("/api/clip", response_class=JSONResponse)