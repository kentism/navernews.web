from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def normalize_article_url(url: str) -> str:
    """Remove analytics parameters without changing article identifiers."""
    cleaned = str(url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return cleaned
    params = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
              if not key.lower().startswith("utm_")]
    return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))
