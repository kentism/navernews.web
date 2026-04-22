import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def time_ago(value):
    if not value:
        return ""

    if isinstance(value, str):
        try:
            dt = parsedate_to_datetime(value)
        except Exception:
            return value
    elif isinstance(value, datetime):
        dt = value
    else:
        return value

    now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
    diff = now - dt
    seconds = diff.total_seconds()

    if seconds < 60:
        return "방금 전"
    if seconds < 3600:
        return f"{int(seconds / 60)}분 전"
    if seconds < 86400:
        return f"{int(seconds / 3600)}시간 전"
    if seconds < 604800:
        return f"{int(seconds / 86400)}일 전"
    return dt.strftime("%Y-%m-%d")


def extract_highlight_keyword(keyword: str) -> str:
    return re.sub(r'([+-][^\s"]+)|(\+"[^"]+")', " ", keyword).strip()
