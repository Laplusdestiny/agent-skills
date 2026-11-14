def paginate(items, page, per_page=10):
    """Return the items on a 1-indexed page."""
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page must be >= 1")
    start = page * per_page
    return items[start:start + per_page]
