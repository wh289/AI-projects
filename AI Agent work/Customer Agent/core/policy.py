"""Deterministic policy. No model calls happen in this file, ever.

Everything here is a pure function of retrieved facts. If you find yourself
wanting to ask the model something inside this module, the design is wrong.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from .models import (
    Claim,
    Customer,
    EscalationTrigger,
    Order,
    OrderItem,
    RefundBreakdown,
    Resolution,
    ResolutionType,
    RiskTier,
    WindowCheck,
)

# --------------------------------------------------------------------------
# Policy constants. Everything tunable lives here, not scattered in logic.
# --------------------------------------------------------------------------

RETURN_WINDOW_DAYS = 30
PLUS_TIER_WINDOW_DAYS = 60

RESTOCKING_FEE_BY_CATEGORY: dict[str, Decimal] = {
    "electronics": Decimal("0.15"),
}

# Reasons where the fault is ours: no fee, shipping refunded.
SELLER_FAULT_REASONS = {"arrived_damaged", "not_as_described", "wrong_item_sent", "faulty"}

STANDARD_RETURN_SHIPPING = Decimal("4.99")

HIGH_VALUE_ESCALATION_THRESHOLD = Decimal("250.00")
INSPECTION_REQUIRED_THRESHOLD = Decimal("100.00")

RISK_ELEVATED_RETURNS_90D = 4
RISK_HIGH_RETURNS_90D = 8


def _money(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# COMPLETE -- worked examples. Read these to pick up the house style.
# --------------------------------------------------------------------------


def check_return_window(
    order: Order, item: OrderItem, customer: Customer, now: Optional[datetime] = None
) -> WindowCheck:
    """Is this item still inside its return window?

    Note that this returns a structured verdict, not a bool. The model needs
    to be able to explain the outcome, and 'False' is not explainable.
    """
    now = now or datetime.now(timezone.utc)
    window = PLUS_TIER_WINDOW_DAYS if customer.tier == "plus" else RETURN_WINDOW_DAYS

    if order.delivered_at is None:
        return WindowCheck(
            within_window=False,
            days_elapsed=None,
            window_days=window,
            reason="Order has not been delivered yet; the return window starts on delivery.",
        )

    elapsed = (now - order.delivered_at).days
    if elapsed <= window:
        return WindowCheck(True, elapsed, window,
                           f"Delivered {elapsed} days ago, inside the {window}-day window.")
    return WindowCheck(False, elapsed, window,
                       f"Delivered {elapsed} days ago, outside the {window}-day window.")


def assess_return_risk(customer: Customer) -> RiskTier:
    """Risk tiering from behavioural history only.

    This is deliberately not a model judgement. Deciding a customer is
    suspicious is an accusation, and accusations need an auditable rule
    that a human can be shown when the customer complains.
    """
    if customer.fraud_flag or customer.returns_last_90_days >= RISK_HIGH_RETURNS_90D:
        return RiskTier.HIGH
    if customer.returns_last_90_days >= RISK_ELEVATED_RETURNS_90D:
        return RiskTier.ELEVATED
    return RiskTier.LOW


# --------------------------------------------------------------------------
# GAP 1 -- warm-up. Implement this first.
# --------------------------------------------------------------------------


def compute_refund(
    item: OrderItem,
    reason_code: str,
    risk_tier: RiskTier,
    quantity: int = 1,
) -> RefundBreakdown:
    """Work out what the customer actually gets back.

    Requirements:
      - gross = unit_price * quantity
      - restocking fee applies from RESTOCKING_FEE_BY_CATEGORY, EXCEPT when
        reason_code is in SELLER_FAULT_REASONS (our fault, no fee)
      - return shipping is refunded only for seller-fault reasons
      - net = gross - restocking_fee + shipping_refunded, never below zero
      - every deduction must append a human-readable string to notes, because
        the model has to explain the number and cannot be trusted to
        reconstruct the arithmetic itself
      - use _money() on every returned Decimal

    Deliberate design point: risk_tier is passed in but must NOT change the
    amount. Money owed is money owed. Risk changes the PATH (inspection,
    escalation), never the entitlement. Work out where you would have been
    tempted to use it, and leave a comment there instead.
    """
    seller_at_fault = reason_code in SELLER_FAULT_REASONS
    gross = _money(item.unit_price * quantity)
    notes = [f"{quantity} x {item.name} at {item.unit_price} each = {gross}."]

    if seller_at_fault:
        restocking_fee = Decimal("0.00")
        shipping_refunded = STANDARD_RETURN_SHIPPING
        notes.append("No restocking fee applied: the return is due to a fault on our side.")
        notes.append(f"Return shipping of {_money(shipping_refunded)} refunded.")
    else:
        fee_rate = RESTOCKING_FEE_BY_CATEGORY.get(item.category, Decimal("0"))
        restocking_fee = _money(gross * fee_rate)
        shipping_refunded = Decimal("0.00")
        if restocking_fee > 0:
            notes.append(
                f"Restocking fee of {int(fee_rate * 100)}% ({_money(restocking_fee)}) "
                f"applied to category '{item.category}'."
            )

    net = max(gross - restocking_fee + shipping_refunded, Decimal("0.00"))

    return RefundBreakdown(
        gross=gross,
        restocking_fee=_money(restocking_fee),
        shipping_refunded=_money(shipping_refunded),
        net=_money(net),
        notes=notes,
    )
   # Risk changes the path (inspection, escalation), not the entitlement.
        


# --------------------------------------------------------------------------
# COMPLETE -- this is the one we talked through. Study it before Gap 2.
# --------------------------------------------------------------------------


def available_resolutions(
    order: Order,
    item: OrderItem,
    customer: Customer,
    reason_code: str,
    now: Optional[datetime] = None,
) -> list[Resolution]:
    """The full set of things that may be offered.

    The model chooses how to SURFACE these conversationally. It never adds
    to this list and never invents an option that is not in it. That is the
    whole point of returning the set from deterministic code.
    """
    window = check_return_window(order, item, customer, now)
    risk = assess_return_risk(customer)
    options: list[Resolution] = []

    if item.final_sale and reason_code not in SELLER_FAULT_REASONS:
        return []

    if not window.within_window and reason_code not in SELLER_FAULT_REASONS:
        return []

    value = item.unit_price
    inspect = value >= INSPECTION_REQUIRED_THRESHOLD or risk != RiskTier.LOW

    options.append(Resolution(ResolutionType.EXCHANGE_SAME_ITEM, "Exchange for the same item",
                              requires_inspection=inspect, estimated_value=value))
    options.append(Resolution(ResolutionType.STORE_CREDIT, "Store credit",
                              requires_inspection=inspect, estimated_value=value))

    if risk != RiskTier.HIGH:
        options.append(Resolution(ResolutionType.REFUND_ORIGINAL_PAYMENT,
                                  "Refund to original payment method",
                                  requires_inspection=inspect, estimated_value=value))

    if item.category == "electronics" and reason_code == "faulty":
        options.append(Resolution(ResolutionType.REPAIR, "Free repair under warranty",
                                  requires_inspection=True, estimated_value=Decimal("0.00")))

    return options


# --------------------------------------------------------------------------
# GAP 2 -- do this after the action layer, not before.
# --------------------------------------------------------------------------


def escalation_required(
    order: Order,
    item: OrderItem,
    customer: Customer,
    refund: Optional[RefundBreakdown],
    claims: list[Claim],
    turn_count: int,
) -> Optional[EscalationTrigger]:
    """Return a trigger if a human must take over, else None.

    Mandatory triggers (mandatory=True). These fire regardless of how well
    the conversation is going, and the model cannot talk its way past them:
      - customer.fraud_flag is set
      - refund net exceeds HIGH_VALUE_ESCALATION_THRESHOLD
      - risk tier is HIGH
      - turn_count exceeds 12 (the conversation is not converging)

    Think carefully about the asymmetry before you write it: the model is
    allowed to REQUEST escalation on top of these, but must never be able to
    suppress one that has already fired. Make that structurally impossible
    rather than relying on the prompt -- if the only thing stopping the model
    from cancelling an escalation is an instruction in the system prompt,
    you have not implemented a guardrail, you have written a suggestion.
    """
    raise NotImplementedError("GAP 2")
