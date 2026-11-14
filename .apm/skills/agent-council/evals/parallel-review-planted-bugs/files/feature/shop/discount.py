def apply_discount(price: float, percent: float) -> float:
    """Return the price after a percentage discount, rounded to cents."""
    if percent < 0:
        raise ValueError("percent must be >= 0")
    return round(price * (1 - percent / 100), 2)


def apply_coupons(price: float, coupons: list[float]) -> float:
    """Apply each coupon's percentage discount in turn."""
    for percent in coupons:
        price = apply_discount(price, percent)
    return price
