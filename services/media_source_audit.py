import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from services.media_source_registry import (
    MEDIA_DOMAIN_MAP,
    MEDIA_MAPPING_CORRECTIONS,
    REVIEWED_MEDIA_DOMAIN_ADDITIONS,
    list_media_mappings,
    normalize_media_domain,
    resolve_media_source,
)


DEFAULT_AUDIT_KEYWORDS = (
    "방송미디어통신심의위원회",
    "방송미디어통신위원회",
    "과방위",
)
NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"
AUDIT_USER_AGENT = "Mozilla/5.0 (compatible; NaverNewsMediaAudit/1.0)"


class _SiteMetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.open_graph_names: list[str] = []
        self.application_names: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        key = (values.get("property") or values.get("name") or "").lower()
        content = values.get("content", "").strip()
        if not content:
            return
        if key == "og:site_name":
            self.open_graph_names.append(content)
        elif key in {"application-name", "apple-mobile-web-app-title"}:
            self.application_names.append(content)


def _clean_source_name(value: str) -> str:
    cleaned = unescape(str(value or ""))
    cleaned = re.sub(r"[\u200b-\u200d\ufeff]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" |-_")


def extract_site_name(html_text: str) -> str:
    """Extract the publisher-controlled site name from article metadata."""
    parser = _SiteMetadataParser()
    try:
        parser.feed(str(html_text or ""))
    except Exception:
        return ""
    names = parser.open_graph_names or parser.application_names
    return _clean_source_name(names[0]) if names else ""


def propose_source_name(metadata_names: Iterable[str]) -> dict[str, object]:
    """Create a proposal only when collected metadata does not conflict."""
    cleaned_names = [_clean_source_name(name) for name in metadata_names]
    cleaned_names = [name for name in cleaned_names if name]
    counts = Counter(cleaned_names)
    if not counts:
        return {
            "proposed_source": "",
            "review_status": "metadata_missing",
            "metadata_names": [],
        }
    if len(counts) > 1:
        return {
            "proposed_source": "",
            "review_status": "metadata_conflict",
            "metadata_names": sorted(counts),
        }
    return {
        "proposed_source": next(iter(counts)),
        "review_status": "metadata_consistent",
        "metadata_names": list(counts),
    }


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _read_json(url: str, headers: dict[str, str], timeout: float = 10) -> dict:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def collect_observed_domains(
    keywords: Iterable[str],
    client_id: str,
    client_secret: str,
    display: int = 100,
) -> tuple[dict[str, list[str]], int]:
    """Collect up to two current article samples for every observed domain."""
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
        "User-Agent": AUDIT_USER_AGENT,
    }
    samples: dict[str, list[str]] = {}
    checked_count = 0
    for keyword in keywords:
        query = urlencode({"query": keyword, "display": display, "start": 1, "sort": "date"})
        payload = _read_json(f"{NAVER_NEWS_API_URL}?{query}", headers)
        items = payload.get("items", [])
        checked_count += len(items)
        for item in items:
            article_url = item.get("originallink") or item.get("link") or ""
            domain = normalize_media_domain(article_url)
            if not domain or not article_url:
                continue
            domain_samples = samples.setdefault(domain, [])
            if article_url not in domain_samples and len(domain_samples) < 2:
                domain_samples.append(article_url)
    return samples, checked_count


def _fetch_site_name(url: str, timeout: float = 8) -> str:
    request = Request(url, headers={"User-Agent": AUDIT_USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(512_000)
            charset = response.headers.get_content_charset() or "utf-8"
        return extract_site_name(payload.decode(charset, errors="replace"))
    except Exception:
        return ""


def audit_unmapped_domains(samples: dict[str, list[str]], max_workers: int = 10) -> list[dict]:
    """Audit only unmapped domains and retain evidence for manual approval."""
    jobs = [
        (domain, article_url)
        for domain, urls in samples.items()
        if not resolve_media_source(domain).matched
        for article_url in urls
    ]
    evidence: dict[str, list[str]] = {}

    def fetch(job: tuple[str, str]) -> tuple[str, str]:
        domain, article_url = job
        return domain, _fetch_site_name(article_url)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for domain, site_name in executor.map(fetch, jobs):
            evidence.setdefault(domain, []).append(site_name)

    rows = []
    for domain in sorted(evidence):
        proposal = propose_source_name(evidence[domain])
        rows.append(
            {
                "domain": domain,
                **proposal,
                "sample_urls": samples.get(domain, []),
            }
        )
    return rows


def render_review_markdown(
    audit_rows: list[dict],
    checked_count: int,
    observed_domain_count: int,
) -> str:
    """Render applied mappings and pending evidence in one review document."""
    lines = [
        "# 매체 도메인 매핑 검토표",
        "",
        f"- 생성 시각: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 검색 표본: 기사 {checked_count}건, 도메인 {observed_domain_count}개",
        f"- 현재 적용 매핑: {len(MEDIA_DOMAIN_MAP)}개",
        f"- 이번 감사 신규 반영: {len(REVIEWED_MEDIA_DOMAIN_ADDITIONS)}개",
        f"- 이번 표본의 미등록 도메인: {len(audit_rows)}개",
        "",
        "## 적용 원칙",
        "",
        "- 검색 결과는 공용 레지스트리의 정확한 도메인부터 확인하고, 없으면 가장 긴 등록 상위 도메인을 사용한다.",
        "- 전혀 모르는 도메인은 매체명을 추정하지 않고 도메인 문자열로 표시한다.",
        "- 감사 도구는 원문 `og:site_name`을 제안 근거로만 사용하며 상수를 자동 수정하지 않는다.",
        "- 재검사는 저장소 루트에서 `python -m services.media_source_audit`로 실행한다.",
        "",
        "## 기존 오매칭 교정",
        "",
        "| 도메인 | 이전 문자열 | 현재 문자열 |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| `{row['domain']}` | {_markdown_cell(row['previous'])} | {_markdown_cell(row['source'])} |"
        for row in MEDIA_MAPPING_CORRECTIONS
    )
    lines.extend(
        [
            "",
            "## 이번 감사 신규 반영",
            "",
            "아래 문자열은 원문 메타데이터와 공식 사이트 제호를 기준으로 반영했으며 사용자가 최종 검토한다.",
            "",
            "| 도메인 | 표시 매체명 |",
            "| --- | --- |",
        ]
    )
    lines.extend(
        f"| `{domain}` | {_markdown_cell(source)} |"
        for domain, source in sorted(REVIEWED_MEDIA_DOMAIN_ADDITIONS.items())
    )
    lines.extend(
        [
            "",
            "## 현재 적용 목록",
            "",
            "| 도메인 | 표시 매체명 |",
            "| --- | --- |",
        ]
    )
    lines.extend(
        f"| `{row['domain']}` | {_markdown_cell(row['source'])} |"
        for row in list_media_mappings()
    )
    lines.extend(
        [
            "",
            "## 미등록 도메인 검토",
            "",
            "`metadata_consistent`도 자동 승인된 값이 아니라 원문 메타데이터 기반 제안이다. 사용자가 확인한 뒤 공용 레지스트리에 반영한다.",
            "",
            "| 도메인 | 제안 매체명 | 상태 | 수집된 메타데이터 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in audit_rows:
        metadata = _markdown_cell(", ".join(row.get("metadata_names", [])) or "-")
        proposed = _markdown_cell(row.get("proposed_source") or "-")
        lines.append(
            f"| `{row['domain']}` | {proposed} | `{row['review_status']}` | {metadata} |"
        )
    lines.append("")
    return "\n".join(lines)


def _markdown_cell(value: object) -> str:
    return str(value or "-").replace("|", "\\|").replace("\n", " ").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit unmapped media domains without auto-approving them.")
    parser.add_argument("--keyword", action="append", dest="keywords")
    parser.add_argument("--display", type=int, default=100)
    parser.add_argument("--output", default="docs/media-domain-map.md")
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[1]
    _load_env_file(repository_root / ".env")
    client_id = os.getenv("NAVER_CLIENT_ID", "").strip()
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise SystemExit("NAVER_CLIENT_ID and NAVER_CLIENT_SECRET are required.")

    samples, checked_count = collect_observed_domains(
        args.keywords or DEFAULT_AUDIT_KEYWORDS,
        client_id,
        client_secret,
        max(1, min(args.display, 100)),
    )
    audit_rows = audit_unmapped_domains(samples)
    document = render_review_markdown(audit_rows, checked_count, len(samples))

    output_path = (repository_root / args.output).resolve()
    if output_path != repository_root and repository_root not in output_path.parents:
        raise SystemExit("Output path must stay inside the repository root.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
    print(f"Wrote {output_path} ({len(audit_rows)} unmapped domains)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
