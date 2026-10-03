"""Pricing, discounts and tax."""
TAX_RATE = 0.08
COUPONS = {"SAVE10": 0.10, "HALF": 0.50}


def apply_discount(amount, coupon=None):
    """Apply a coupon code; unknown coupons are ignored."""
    rate = COUPONS.get(coupon, 0.0)
    return amount * (1 - rate)
