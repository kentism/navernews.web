import asyncio
from dataclasses import dataclass, field

from app_config import MAX_NOTIFICATION_HISTORY, NOTIFICATION_HISTORY_TTL_SECONDS, POLLING_INTERVAL, WATCHER_STALE_SECONDS
from app_logging import get_logger
from services.news_service import NewsServiceError, fetch_news, get_naver_api_headers

logger = get_logger("monitoring")


@dataclass
class MonitoringState:
    search_cache: dict[str, list] = field(default_factory=dict)
    watch_registry: dict[str, set[str]] = field(default_factory=dict)
    sse_connections: dict[str, asyncio.Queue] = field(default_factory=dict)
    last_seen_clients: dict[str, float] = field(default_factory=dict)
    notification_history: list[tuple[float, str, str]] = field(default_factory=list)


state = MonitoringState()


def cache_search_results(keyword, items):
    key = f"{keyword}_1"
    state.search_cache.pop(key, None)
    state.search_cache[key] = items
    while len(state.search_cache) > 128:
        state.search_cache.pop(next(iter(state.search_cache)))


async def poll_naver_news_task():
    """Poll watched searches; one failed keyword does not stop the others."""
    while True:
        now = asyncio.get_running_loop().time()
        state.notification_history[:] = [item for item in state.notification_history
                                         if now - item[0] < NOTIFICATION_HISTORY_TTL_SECONDS]
        for keyword in list(state.watch_registry):
            watchers = set(state.watch_registry.get(keyword, set()))
            online = watchers.intersection(state.sse_connections)
            if not online:
                if all(now - state.last_seen_clients.get(cid, 0) >= WATCHER_STALE_SECONDS for cid in watchers):
                    state.watch_registry.pop(keyword, None)
                continue
            try:
                items = await fetch_news(keyword, await get_naver_api_headers())
            except NewsServiceError:
                logger.warning("Watched search temporarily unavailable")
                continue
            previous = state.search_cache.get(f"{keyword}_1", [])
            cache_search_results(keyword, items)
            if not items or not previous or items[0].link == previous[0].link:
                continue
            message = f"[{keyword}] 관련 새 기사가 감지되었습니다."
            state.notification_history.append((now, keyword, message))
            state.notification_history[:] = state.notification_history[-MAX_NOTIFICATION_HISTORY:]
            for client_id in online:
                queue = state.sse_connections.get(client_id)
                if queue:
                    queue.put_nowait(message)
        for client_id, last_seen in list(state.last_seen_clients.items()):
            if client_id not in state.sse_connections and now - last_seen > WATCHER_STALE_SECONDS:
                state.last_seen_clients.pop(client_id, None)
        await asyncio.sleep(POLLING_INTERVAL)
