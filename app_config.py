import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

APP_ACCESS_KEY = os.getenv("APP_ACCESS_KEY", "32195114")
DEFAULT_KEYWORDS = [
    keyword.strip()
    for keyword in os.getenv(
        "DEFAULT_KEYWORDS",
        "방송미디어통신심의위원회,방송미디어통신위원회,과방위",
    ).split(",")
    if keyword.strip()
]

POLLING_INTERVAL = int(os.getenv("POLLING_INTERVAL_SECONDS", "30"))
WATCHER_STALE_SECONDS = int(os.getenv("WATCHER_STALE_SECONDS", "120"))
NOTIFICATION_HISTORY_TTL_SECONDS = int(os.getenv("NOTIFICATION_HISTORY_TTL_SECONDS", "120"))
MAX_NOTIFICATION_HISTORY = int(os.getenv("MAX_NOTIFICATION_HISTORY", "50"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
HTTP_RETRY_COUNT = int(os.getenv("HTTP_RETRY_COUNT", "3"))
