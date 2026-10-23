import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from markupsafe import Markup, escape


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


def highlight_keyword(text: str, keyword: str) -> Markup:
    """Escape external text before adding the application's own highlight tags."""
    value = str(text or "")
    term = extract_highlight_keyword(keyword or "")
    if not term:
        return escape(value)
    pieces = []
    position = 0
    for match in re.finditer(re.escape(term), value, re.IGNORECASE):
        pieces.extend([escape(value[position:match.start()]), Markup("<mark>"),
                       escape(match.group()), Markup("</mark>")])
        position = match.end()
    pieces.append(escape(value[position:]))
    return Markup("").join(pieces)
