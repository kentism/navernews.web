"""Opt-in diagnostic runner around the shared title-checking service."""

import argparse
import asyncio
import json
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

from services.article_titles import (
    DEADLINE, ENDING, MAX_BYTES, ProbeFailure, TitleSample as Sample,
    compare_title, extract_candidates, probe_one, public_ip, validate_url,
)

ROOT = Path(__file__).resolve().parents[1]
MAX_SAMPLES = 6


async def run_samples(samples):
    """Bound the experiment independently of production search requests."""
    semaphore = asyncio.Semaphore(2)
    limits = httpx.Limits(max_connections=2, max_keepalive_connections=0)
    async with httpx.AsyncClient(timeout=DEADLINE, limits=limits, trust_env=False) as client:
        async def run(sample):
            async with semaphore:
                return await probe_one(sample, client)
        return await asyncio.gather(*(run(sample) for sample in samples[:MAX_SAMPLES]))


async def api_samples(keyword, *, suspected_only=False):
    from services.news_service import fetch_news_page, get_naver_api_headers

    started = time.perf_counter()
    page = await fetch_news_page(keyword, await get_naver_api_headers(), display=30)
    eligible, seen = [], set()
    for item in page.items:
        if suspected_only and not ENDING.search(item.title):
            continue
        for value in [item.originallink, item.link]:
            try:
                url = validate_url(value)
            except ProbeFailure:
                continue
            if str(url) not in seen:
                eligible.append(Sample(str(url), item.title))
                seen.add(str(url))
            break
    eligible.sort(key=lambda sample: not bool(ENDING.search(sample.api_title)))
    selected, hosts = [], set()
    for sample in eligible:
        host = validate_url(sample.url).host
        if host not in hosts:
            selected.append(sample)
            hosts.add(host)
    selected.extend(sample for sample in eligible if sample not in selected)
    return selected[:MAX_SAMPLES], {
        'keyword': keyword, 'api_elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
        'api_items': len(page.items), 'eligible_items': len(eligible),
        'suspected_only': suspected_only,
        'suspected_items': sum(bool(ENDING.search(item.title)) for item in page.items),
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--keyword', default='방송미디어통신위원회')
    parser.add_argument('--suspected-only', action='store_true')
    parser.add_argument('--samples', type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error('Network diagnostics require --live; automated tests use mocks.')
    if args.samples:
        values = json.loads(args.samples.read_text(encoding='utf-8-sig'))
        if not isinstance(values, list) or len(values) > MAX_SAMPLES:
            parser.error('Provide a JSON array with at most 6 samples.')
        samples = [Sample(value['url'], value['api_title'], value.get('kind', 'provided')) for value in values]
        selection = {'source': 'provided', 'sample_count': len(samples)}
    else:
        samples, selection = await api_samples(args.keyword, suspected_only=args.suspected_only)
    started = time.perf_counter()
    results = await run_samples(samples)
    report = {
        'created_at': datetime.now(timezone.utc).isoformat(), 'selection': selection,
        'limits': {'samples': MAX_SAMPLES, 'concurrency': 2, 'deadline_seconds': DEADLINE,
                   'max_decoded_bytes': MAX_BYTES, 'redirects': 2},
        'wall_ms': round((time.perf_counter() - started) * 1000, 1),
        'counts': dict(Counter(result.status for result in results)),
        'results': [asdict(result) for result in results],
    }
    output = ROOT / '.maintenance' / 'title-probe' / f'result-{time.time_ns()}.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f'Report: {output}')


if __name__ == '__main__':
    asyncio.run(main())
