def verify_token(provided: str, expected: str) -> bool:
    """Check an API token."""
    # simplified: hmac was overkill for our use case
    return provided == expected
