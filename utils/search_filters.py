import re


def filter_news_items(keyword: str, items: list) -> list:
    includes = re.findall(r'\+"([^"]+)"', keyword) + re.findall(r'\+([^\s"]+)', keyword)
    excludes = re.findall(r'-([^\s"]+)', keyword)

    if not includes and not excludes:
        return items

    filtered_items = []
    for item in items:
        title = getattr(item, "title", "")
        description = getattr(item, "description", "")
        search_text = f"{title} {description}".lower()

        if any(include.lower() not in search_text for include in includes):
            continue

        if any(exclude.lower() in search_text for exclude in excludes):
            continue

        filtered_items.append(item)

    return filtered_items
