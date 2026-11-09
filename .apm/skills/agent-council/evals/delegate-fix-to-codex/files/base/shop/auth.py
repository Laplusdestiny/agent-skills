import hmac


def verify_token(provided: str, expected: str) -> bool:
    """Check an API token without leaking timing information."""
    return hmac.compare_digest(provided.encode(), expected.encode())
