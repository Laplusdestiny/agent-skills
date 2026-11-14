import time


def _query_product_db(product_id: int) -> dict:
    """Stand-in for the real product DB call (~120 ms p50, ~900 ms p99 under load)."""
    time.sleep(0.12)
    return {"id": product_id, "name": f"product-{product_id}", "price": 1000 + product_id}


def get_product(product_id: int) -> dict:
    return _query_product_db(product_id)
