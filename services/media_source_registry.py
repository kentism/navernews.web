from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


# Search results use this reviewed registry only. Newly discovered domains must be
# audited separately before being added here.
BASE_MEDIA_DOMAIN_MAP = {
    "asiatoday.co.kr": "아시아투데이",
    "biz.chosun.com": "조선비즈",
    "biz.heraldcorp.com": "헤럴드경제",
    "biz.sbs.co.kr": "SBS Biz",
    "bloter.net": "블로터",
    "busan.com": "부산일보",
    "chosun.com": "조선일보",
    "daily.hankooki.com": "데일리한국",
    "dailian.co.kr": "데일리안",
    "ddaily.co.kr": "디지털데일리",
    "digitaltoday.co.kr": "디지털투데이",
    "donga.com": "동아일보",
    "dt.co.kr": "디지털타임스",
    "edaily.co.kr": "이데일리",
    "etnews.com": "전자신문",
    "etoday.co.kr": "이투데이",
    "fnnews.com": "파이낸셜뉴스",
    "hani.co.kr": "한겨레",
    "hankookilbo.com": "한국일보",
    "hankyung.com": "한국경제",
    "ichannela.com": "채널A",
    "imaeil.com": "매일신문",
    "imnews.imbc.com": "MBC",
    "inews24.com": "아이뉴스24",
    "insight.co.kr": "인사이트",
    "it.chosun.com": "IT조선",
    "jibs.co.kr": "JIBS",
    "jnilbo.com": "전남일보",
    "jnnews.co.kr": "전남인터넷신문",
    "joongang.co.kr": "중앙일보",
    "joongang.joins.com": "중앙일보",
    "journalist.or.kr": "기자협회보",
    "kado.net": "강원도민일보",
    "khan.co.kr": "경향신문",
    "kmib.co.kr": "국민일보",
    "kookje.co.kr": "국제신문",
    "kukinews.com": "쿠키뉴스",
    "kyeongbuk.co.kr": "경북일보",
    "kyeonggi.com": "경기일보",
    "kyeongin.com": "경인일보",
    "kyongnam.com": "경남신문",
    "mbn.co.kr": "MBN",
    "mbn.mk.co.kr": "MBN",
    "mediatoday.co.kr": "미디어오늘",
    "mediaus.co.kr": "미디어스",
    "mk.co.kr": "매일경제",
    "moneys.co.kr": "머니S",
    "mt.co.kr": "머니투데이",
    "munhwa.com": "문화일보",
    "naeil.com": "내일신문",
    "newdaily.co.kr": "뉴데일리",
    "news.ajunews.com": "아주경제",
    "news.busan.com": "부산일보",
    "news.daum.net": "다음",
    "news.ebs.co.kr": "EBS",
    "news.edaily.co.kr": "이데일리",
    "news.g-enews.com": "글로벌이코노믹",
    "news.hankyung.com": "한국경제",
    "news.heraldcorp.com": "헤럴드경제",
    "news.imaeil.com": "매일신문",
    "news.joins.com": "중앙일보",
    "news.jtbc.co.kr": "JTBC",
    "news.kbs.co.kr": "KBS",
    "news.khan.co.kr": "경향신문",
    "news.kmib.co.kr": "국민일보",
    "news.kukinews.com": "쿠키뉴스",
    "news.mbc.co.kr": "MBC",
    "news.mt.co.kr": "머니투데이",
    "news.mtn.co.kr": "머니투데이방송",
    "news.naver.com": "네이버",
    "news.sbs.co.kr": "SBS",
    "news.tf.co.kr": "더팩트",
    "news.tvchosun.com": "TV조선",
    "news.unn.net": "한국대학신문",
    "news.wowtv.co.kr": "한국경제TV",
    "news1.kr": "뉴스1",
    "newsis.com": "뉴시스",
    "newscj.com": "천지일보",
    "newspim.com": "뉴스핌",
    "newstapa.org": "뉴스타파",
    "newstomato.com": "뉴스토마토",
    "nocutnews.co.kr": "노컷뉴스",
    "nownews.seoul.co.kr": "나우뉴스",
    "ohmynews.com": "오마이뉴스",
    "pdjournal.com": "PD저널",
    "pressian.com": "프레시안",
    "radio.ytn.co.kr": "YTN",
    "sedaily.com": "서울경제",
    "segye.com": "세계일보",
    "seoul.co.kr": "서울신문",
    "sisajournal-e.com": "시사저널e",
    "sisajournal.com": "시사저널",
    "sports.chosun.com": "스포츠조선",
    "sports.donga.com": "스포츠동아",
    "sports.kbs.co.kr": "KBS",
    "sports.khan.co.kr": "스포츠경향",
    "sports.mk.co.kr": "매일경제 스포츠",
    "sports.sbs.co.kr": "SBS 스포츠",
    "sports.seoul.co.kr": "스포츠서울",
    "thebell.co.kr": "더벨",
    "topstarnews.net": "톱스타뉴스",
    "view.asiae.co.kr": "아시아경제",
    "weekly.chosun.com": "주간조선",
    "wowtv.co.kr": "한국경제TV",
    "yna.co.kr": "연합뉴스",
    "yonhapnewstv.co.kr": "연합뉴스TV",
    "ytn.co.kr": "YTN",
    "zdnet.co.kr": "지디넷코리아",
}


REVIEWED_MEDIA_DOMAIN_ADDITIONS = {
    "aitimes.kr": "인공지능신문",
    "ajunews.com": "아주경제",
    "apnews.kr": "AP신문",
    "banronbodo.com": "반론보도닷컴",
    "bizwnews.com": "비즈월드",
    "breaknews.com": "브레이크뉴스",
    "businesspost.co.kr": "비즈니스포스트",
    "byline.network": "바이라인네트워크",
    "cbci.co.kr": "CBC뉴스",
    "celuvmedia.com": "셀럽미디어",
    "cjb.co.kr": "CJB청주방송",
    "daejonilbo.com": "대전일보",
    "danbinews.com": "단비뉴스",
    "dnews.co.kr": "대한경제",
    "economist.co.kr": "이코노미스트",
    "econovill.com": "이코노믹리뷰",
    "ekn.kr": "에너지경제신문",
    "enews.imbc.com": "iMBC 연예",
    "enewstoday.co.kr": "이뉴스투데이",
    "epnc.co.kr": "테크월드",
    "facttv.kr": "팩트TV",
    "g1tv.co.kr": "G1방송",
    "gamevu.co.kr": "게임뷰",
    "goodkyung.com": "굿모닝경제",
    "goodnews1.com": "데일리굿뉴스",
    "gukjenews.com": "국제뉴스",
    "idaegu.co.kr": "대구신문",
    "ikld.kr": "국토일보",
    "ilyo.co.kr": "일요신문",
    "incheonilbo.com": "인천일보",
    "itdaily.kr": "아이티데일리",
    "journal.kobeta.com": "방송기술저널",
    "kbmaeil.com": "경북매일",
    "kihoilbo.co.kr": "기호일보",
    "kwnews.co.kr": "강원일보",
    "lawleader.co.kr": "로리더",
    "m-economynews.com": "M이코노미뉴스",
    "mdilbo.com": "무등일보",
    "metroseoul.co.kr": "메트로신문",
    "mydaily.co.kr": "마이데일리",
    "mygoyang.com": "고양신문",
    "n.news.naver.com": "네이버",
    "natv.go.kr": "국회방송",
    "news.cpbc.co.kr": "CPBC",
    "news.einfomax.co.kr": "연합인포맥스",
    "news.ifm.kr": "경인방송",
    "news.lghellovision.net": "LG헬로비전",
    "news.skbroadband.com": "B tv news",
    "news2day.co.kr": "뉴스투데이",
    "newsdream.kr": "뉴스드림",
    "newsprime.co.kr": "프라임경제",
    "newsworks.co.kr": "뉴스웍스",
    "obsnews.co.kr": "OBS경인TV",
    "pennmike.com": "펜앤마이크",
    "pharmnews.com": "팜뉴스",
    "pinpointnews.co.kr": "핀포인트뉴스",
    "polinews.co.kr": "폴리뉴스",
    "sateconomy.co.kr": "토요경제",
    "shinailbo.co.kr": "신아일보",
    "sidae.com": "동행미디어 시대",
    "sisaweek.com": "시사위크",
    "sportsworldi.com": "스포츠월드",
    "spotvnews.co.kr": "SPOTV NEWS",
    "stoo.com": "스포츠투데이",
    "the-pr.co.kr": "더피알",
    "thepublic.kr": "더퍼블릭",
    "thereport.co.kr": "더리포트",
    "tvdaily.co.kr": "티브이데일리",
    "tvreport.co.kr": "TV리포트",
    "ulsanpress.net": "울산신문",
    "viva100.com": "브릿지경제",
    "yeongnam.com": "영남일보",
    "ziksir.com": "직썰",
}


MEDIA_MAPPING_CORRECTIONS = (
    {"domain": "asiatoday.co.kr", "previous": "아시아경제", "source": "아시아투데이"},
    {"domain": "biz.sbs.co.kr", "previous": "SBSBiz", "source": "SBS Biz"},
    {"domain": "jnilbo.com", "previous": "전북일보", "source": "전남일보"},
    {"domain": "jnnews.co.kr", "previous": "전남일보", "source": "전남인터넷신문"},
    {"domain": "nownews.seoul.co.kr", "previous": "서울신문", "source": "나우뉴스"},
    {"domain": "daejoilbo.com", "previous": "대전일보", "source": "삭제(오타 도메인)"},
)


MEDIA_DOMAIN_MAP = {
    **BASE_MEDIA_DOMAIN_MAP,
    **REVIEWED_MEDIA_DOMAIN_ADDITIONS,
}


@dataclass(frozen=True)
class MediaSourceResolution:
    domain: str
    source: str
    matched: bool
    match_method: str
    matched_domain: Optional[str] = None


def normalize_media_domain(value: str) -> str:
    """Normalize a URL or hostname for media registry lookup."""
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    domain = (parsed.hostname or "").strip(".")
    return domain[4:] if domain.startswith("www.") else domain


def _meaningful_explicit_source(explicit_source: str, domain: str) -> str:
    source = str(explicit_source or "").strip()
    if not source:
        return ""
    source_domain = normalize_media_domain(source)
    if source.lower() == domain or source_domain == domain:
        return ""
    return source


def resolve_media_source(domain_or_url: str, explicit_source: str = "") -> MediaSourceResolution:
    """Resolve a display name without guessing unknown media organizations."""
    domain = normalize_media_domain(domain_or_url)
    supplied = _meaningful_explicit_source(explicit_source, domain)
    if supplied:
        return MediaSourceResolution(domain, supplied, True, "explicit_source")

    matches = [
        registered_domain
        for registered_domain in MEDIA_DOMAIN_MAP
        if domain == registered_domain or domain.endswith(f".{registered_domain}")
    ]
    if matches:
        matched_domain = max(matches, key=len)
        method = "exact_domain" if matched_domain == domain else "parent_domain"
        return MediaSourceResolution(
            domain,
            MEDIA_DOMAIN_MAP[matched_domain],
            True,
            method,
            matched_domain,
        )

    return MediaSourceResolution(domain, domain, False, "unmapped_domain")


def list_media_mappings() -> list[dict[str, str]]:
    """Return deterministic rows suitable for user review and documentation."""
    return [
        {"domain": domain, "source": MEDIA_DOMAIN_MAP[domain]}
        for domain in sorted(MEDIA_DOMAIN_MAP)
    ]
