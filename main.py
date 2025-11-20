import httpx, html, os
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from bs4 import BeautifulSoup
from pydantic import BaseModel
import re
import uuid
from typing import List
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime

# ----------------------------
# 기본 설정
# ----------------------------
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
    raise ValueError("네이버 API 환경변수(NAVER_CLIENT_ID, NAVER_CLIENT_SECRET)가 설정되지 않았습니다.")


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

# 메모리 기반 저장소
CLIPPINGS = {}  # {clip_id: {"title": "", "url": "", "content": "", "created_at": ""}}
SEARCH_CACHE = {}  # {keyword: [items]}


# ----------------------------
# Pydantic 모델
# ----------------------------
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
# 네이버 뉴스 검색 (최신순, 페이징)
# ----------------------------
async def fetch_news(keyword: str, start: int = 1, display: int = 20):
    url = "https://openapi.naver.com/v1/search/news.json"

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    params = {
        "query": keyword,
        "display": display,
        "start": start,
        "sort": "date"  # 최신순 정렬
    }

    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json()

    items = []
    for item in data.get("items", []):
        clean_title = html.unescape(re.sub(r"<[^>]*>", "", item.get("title", "")))
        clean_desc = html.unescape(re.sub(r"<[^>]*>", "", item.get("description", "")))
        origin = item.get("originallink") or item.get("link") or ""
        # domain 추출 (www. 제거)
        source = item.get("source", "")
        netloc = urlparse(origin).netloc or ""
        domain = netloc.replace("www.", "")
        # pubDate 파싱 및 포맷
        raw_pub = item.get("pubDate", "")
        formatted_pub = ""
        if raw_pub:
            try:
                dt = parsedate_to_datetime(raw_pub)
                formatted_pub = f"{dt.year}년 {dt.month}월 {dt.day}일 {dt.hour}시 {dt.minute}분"
            except Exception:
                formatted_pub = raw_pub
        
        if not source:
            source = DOMAIN_MAP.get(domain, domain)

        items.append(
            NewsItem(
                title=clean_title,
                link=item.get("link", ""),
                description=clean_desc,
                originallink=item.get("originallink", ""),
                source=source,
                pubDate=raw_pub,
                domain=domain,
                formatted_pubdate=formatted_pub
            )
        )
    
    # 검색 결과 캐싱
    SEARCH_CACHE[keyword] = items
    return items


# ----------------------------
# 기사 본문 파싱
# ----------------------------
async def parse_article(url: str) -> str:
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        response = await client.get(url)
        html_content = response.text

    soup = BeautifulSoup(html_content, "html.parser")

    # 여러 패턴 탐색 (뉴스 사이트마다 다름)
    candidates = [
        {"tag": "div", "class": "article_body"},
        {"tag": "div", "class": "newsct_article"},
        {"tag": "div", "class": "go_trans"},
        {"tag": "article", "class": None},
        {"tag": "div", "class": "article"},
    ]

    for c in candidates:
        section = soup.find(c["tag"], class_=c["class"])
        if section:
            text = section.get_text(" ", strip=True)
            if len(text) > 80:
                return text

    # fallback — og:description
    og_desc = soup.find("meta", property="og:description")
    if og_desc:
        return og_desc.get("content", "")

    # 최종 fallback — 전체 텍스트
    return soup.get_text(" ", strip=True)


# ----------------------------
# 라우팅
# ----------------------------

# 메인 페이지 (탭 기반 UI)
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# 검색 API (페이징 지원)
@app.post("/api/search", response_class=JSONResponse)
async def search_api(keyword: str = Form(...), start: int = Form(default=1)):
    """
    검색 결과를 JSON으로 반환 (무한 스크롤용)
    """
    items = await fetch_news(keyword, start=start, display=20)
    return {
        "items": [
            {
                "title": item.title,
                "link": item.link,
                "description": item.description,
                "originallink": item.originallink,
                "source": item.source,
                "pubDate": item.pubDate,
                "domain": item.domain,
                "formatted_pubdate": item.formatted_pubdate
            } for item in items
        ],
        "total": len(items)
    }


# 검색 결과 HTML 렌더링 (HTMX용)
@app.post("/search-results", response_class=HTMLResponse)
async def search_results(request: Request, keyword: str = Form(...), start: int = Form(default=1)):
    items = await fetch_news(keyword, start=start, display=20)
    return templates.TemplateResponse(
        "search_results.html",
        {
            "request": request,
            "items": items,
            "keyword": keyword,
            "start": start + 20
        },
    )


# 기사 본문 파싱 → 상세 뷰
@app.post("/article-detail", response_class=HTMLResponse)
async def article_detail(request: Request, url: str = Form(...), title: str = Form(...)):
    content = await parse_article(url)
    return templates.TemplateResponse(
        "article_detail.html",
        {
            "request": request,
            "title": title,
            "url": url,
            "content": content,
        },
    )


# 클리핑 저장
@app.post("/api/clip", response_class=JSONResponse)
async def clip_article(title: str = Form(...), url: str = Form(...), content: str = Form(...)):
    clip_id = str(uuid.uuid4())
    from datetime import datetime

    CLIPPINGS[clip_id] = {
        "title": title,
        "url": url,
        "content": content,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    return {"success": True, "clip_id": clip_id, "message": "클리핑이 저장되었습니다."}


# 클리핑 목록 HTML 렌더링
@app.get("/clippings-tab", response_class=HTMLResponse)
async def clippings_tab(request: Request):
    return templates.TemplateResponse(
        "clippings_tab.html",
        {
            "request": request, 
            "clips": dict(sorted(CLIPPINGS.items(), key=lambda item: item[1]['created_at'], reverse=True))
        },
    )


# 클리핑 상세 뷰
@app.get("/clips/{clip_id}", response_class=HTMLResponse)
async def clip_detail(request: Request, clip_id: str):
    clip = CLIPPINGS.get(clip_id)
    if not clip:
        return "<p>클리핑을 찾을 수 없습니다.</p>"
    
    return templates.TemplateResponse(
        "clip_detail.html",
        {"request": request, "clip": clip, "clip_id": clip_id},
    )


# 클리핑 삭제
@app.delete("/api/clip/{clip_id}", response_class=JSONResponse)
async def delete_clip(clip_id: str):
    if clip_id in CLIPPINGS:
        del CLIPPINGS[clip_id]
        return {"success": True, "message": "클리핑이 삭제되었습니다."}
    return {"success": False, "message": "클리핑을 찾을 수 없습니다."}


# 모든 클리핑 삭제
@app.delete("/api/clips/all", response_class=JSONResponse)
async def delete_all_clips():
    global CLIPPINGS
    CLIPPINGS.clear()
    return {"success": True, "message": "모든 클리핑이 삭제되었습니다."}
