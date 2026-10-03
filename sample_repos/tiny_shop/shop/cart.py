"""Shopping cart logic."""
from .pricing import apply_discount, TAX_RATE


class EmptyCartError(Exception):
    """Raised when checkout is attempted with no items."""


class Cart:
    def __init__(self):
        self.items = []  # list of (name, unit_price, qty)

    def add_item(self, name, unit_price, qty=1):
        if qty <= 0:
            raise ValueError("qty must be positive")
        self.items.append((name, unit_price, qty))

    def subtotal(self):
        return sum(price * qty for _, price, qty in self.items)

    def checkout(self, coupon=None):
        if not self.items:
            raise EmptyCartError("cannot checkout an empty cart")
        total = apply_discount(self.subtotal(), coupon)
        return round(total * (1 + TAX_RATE), 2)
