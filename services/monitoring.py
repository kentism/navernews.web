import asyncio
from dataclasses import dataclass, field


@dataclass
class MonitoringState:
    search_cache: dict[str, list] = field(default_factory=dict)
    watch_registry: dict[str, set[str]] = field(default_factory=dict)
    sse_connections: dict[str, asyncio.Queue] = field(default_factory=dict)
    last_seen_clients: dict[str, float] = field(default_factory=dict)
    notification_history: list[tuple[float, str, str]] = field(default_factory=list)


state = MonitoringState()
