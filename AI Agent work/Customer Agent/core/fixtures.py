"""Fake backend. Stands in for order management, CRM and payments.

Deliberately hand-built so the eval harness has known-answer cases:
each order is designed to exercise a different policy branch.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from .models import Customer, Order, OrderItem

NOW = datetime.now(timezone.utc)


def _days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


CUSTOMERS: dict[str, Customer] = {
    "CUST-001": Customer("CUST-001", "Amara Osei", "standard", 1, 12),
    "CUST-002": Customer("CUST-002", "Tom Brandt", "plus", 6, 40),  # elevated risk
    "CUST-003": Customer("CUST-003", "Priya Raman", "standard", 11, 14, fraud_flag=True),
    "CUST-004": Customer("CUST-004", "Joe Kelleher", "plus", 0, 3),
}

ORDERS: dict[str, Order] = {
    # Comfortably in window, low-value, clean case
    "ORD-1001": Order(
        "ORD-1001",
        "CUST-001",
        _days_ago(14),
        _days_ago(10),
        [OrderItem("IT-1", "SKU-TSH-M", "Merino base layer", "apparel", Decimal("48.00"), 1)],
    ),
    # Just outside the window -- tests the boundary
    "ORD-1002": Order(
        "ORD-1002",
        "CUST-001",
        _days_ago(40),
        _days_ago(34),
        [OrderItem("IT-1", "SKU-BOOT-9", "Approach shoes", "footwear", Decimal("120.00"), 1)],
    ),
    # High value + electronics restocking fee + escalation threshold
    "ORD-1003": Order(
        "ORD-1003",
        "CUST-002",
        _days_ago(9),
        _days_ago(5),
        [
            OrderItem("IT-1", "SKU-WATCH-X", "GPS sports watch", "electronics", Decimal("389.00"), 1),
            OrderItem("IT-2", "SKU-STRAP", "Spare strap", "accessories", Decimal("22.00"), 2),
        ],
    ),
    # Final sale item -- policy must refuse regardless of how it is asked
    "ORD-1004": Order(
        "ORD-1004",
        "CUST-004",
        _days_ago(5),
        _days_ago(2),
        [OrderItem("IT-1", "SKU-CLR-TENT", "Clearance 2-person tent", "outdoor",
                   Decimal("95.00"), 1, final_sale=True)],
    ),
    # Not yet delivered -- window has not started
    "ORD-1005": Order(
        "ORD-1005",
        "CUST-003",
        _days_ago(3),
        None,
        [OrderItem("IT-1", "SKU-ROPE-60", "60m climbing rope", "outdoor", Decimal("165.00"), 1)],
    ),
}


def get_order(order_id: str) -> Optional[Order]:
    return ORDERS.get(order_id.strip().upper())


def get_customer(customer_id: str) -> Optional[Customer]:
    return CUSTOMERS.get(customer_id.strip().upper())


def orders_for_customer(customer_id: str) -> list[Order]:
    return [o for o in ORDERS.values() if o.customer_id == customer_id]
