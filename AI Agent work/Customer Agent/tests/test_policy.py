"""Contract for the policy gaps. Run these; make them pass.

    pytest tests/test_policy.py -v
"""

from decimal import Decimal

import pytest

from core import fixtures, policy
from core.models import Claim, RiskTier

ORDER_ELECTRONICS = "ORD-1003"


def _watch():
    order = fixtures.get_order(ORDER_ELECTRONICS)
    return order, order.item("IT-1")


# --------------------------------------------------------------------------
# GAP 1: compute_refund
# --------------------------------------------------------------------------


def test_refund_applies_restocking_fee_to_electronics():
    _, watch = _watch()
    r = policy.compute_refund(watch, "changed_mind", RiskTier.LOW)
    assert r.gross == Decimal("389.00")
    assert r.restocking_fee == Decimal("58.35")  # 15%
    assert r.net == Decimal("330.65")


def test_refund_waives_fee_when_fault_is_ours():
    _, watch = _watch()
    r = policy.compute_refund(watch, "arrived_damaged", RiskTier.LOW)
    assert r.restocking_fee == Decimal("0.00")
    assert r.shipping_refunded == policy.STANDARD_RETURN_SHIPPING
    assert r.net == Decimal("393.99")


def test_no_restocking_fee_on_non_electronics():
    order = fixtures.get_order("ORD-1001")
    r = policy.compute_refund(order.item("IT-1"), "doesnt_fit", RiskTier.LOW)
    assert r.restocking_fee == Decimal("0.00")
    assert r.net == Decimal("48.00")


def test_risk_tier_does_not_change_the_amount():
    """Money owed is money owed. Risk changes the path, not the entitlement."""
    _, watch = _watch()
    low = policy.compute_refund(watch, "changed_mind", RiskTier.LOW)
    high = policy.compute_refund(watch, "changed_mind", RiskTier.HIGH)
    assert low.net == high.net


def test_refund_explains_every_deduction():
    _, watch = _watch()
    r = policy.compute_refund(watch, "changed_mind", RiskTier.LOW)
    assert r.notes, "the model cannot explain a number you have not explained to it"
    assert any("restocking" in n.lower() for n in r.notes)


def test_refund_respects_quantity():
    order = fixtures.get_order(ORDER_ELECTRONICS)
    strap = order.item("IT-2")
    r = policy.compute_refund(strap, "changed_mind", RiskTier.LOW, quantity=2)
    assert r.gross == Decimal("44.00")


def test_refund_never_negative():
    order = fixtures.get_order("ORD-1001")
    r = policy.compute_refund(order.item("IT-1"), "changed_mind", RiskTier.LOW)
    assert r.net >= Decimal("0.00")


# --------------------------------------------------------------------------
# GAP 2: escalation_required
# --------------------------------------------------------------------------


def test_fraud_flag_forces_mandatory_escalation():
    order = fixtures.get_order("ORD-1005")
    customer = fixtures.get_customer("CUST-003")
    trigger = policy.escalation_required(order, order.item("IT-1"), customer, None, [], 1)
    assert trigger is not None
    assert trigger.mandatory is True


def test_high_value_refund_escalates():
    order = fixtures.get_order(ORDER_ELECTRONICS)
    watch = order.item("IT-1")
    customer = fixtures.get_customer("CUST-004")
    refund = policy.compute_refund(watch, "changed_mind", RiskTier.LOW)
    trigger = policy.escalation_required(order, watch, customer, refund, [], 1)
    assert trigger is not None and trigger.mandatory


def test_clean_low_value_case_does_not_escalate():
    order = fixtures.get_order("ORD-1001")
    item = order.item("IT-1")
    customer = fixtures.get_customer("CUST-001")
    refund = policy.compute_refund(item, "doesnt_fit", RiskTier.LOW)
    assert policy.escalation_required(order, item, customer, refund, [], 2) is None


def test_runaway_conversation_escalates():
    order = fixtures.get_order("ORD-1001")
    item = order.item("IT-1")
    customer = fixtures.get_customer("CUST-001")
    trigger = policy.escalation_required(order, item, customer, None, [], turn_count=15)
    assert trigger is not None and trigger.mandatory


# --------------------------------------------------------------------------
# Already passing -- regression cover for the complete functions.
# --------------------------------------------------------------------------


def test_undelivered_order_has_not_started_its_window():
    order = fixtures.get_order("ORD-1005")
    customer = fixtures.get_customer("CUST-003")
    check = policy.check_return_window(order, order.item("IT-1"), customer)
    assert check.within_window is False
    assert check.days_elapsed is None


def test_plus_tier_gets_the_longer_window():
    order = fixtures.get_order("ORD-1002")
    standard = fixtures.get_customer("CUST-001")
    plus = fixtures.get_customer("CUST-004")
    item = order.item("IT-1")
    assert policy.check_return_window(order, item, standard).within_window is False
    assert policy.check_return_window(order, item, plus).within_window is True


def test_final_sale_offers_nothing_unless_our_fault():
    order = fixtures.get_order("ORD-1004")
    item = order.item("IT-1")
    customer = fixtures.get_customer("CUST-004")
    assert policy.available_resolutions(order, item, customer, "changed_mind") == []
    assert policy.available_resolutions(order, item, customer, "faulty") != []


def test_fraud_flag_forces_high_risk_tier():
    assert policy.assess_return_risk(fixtures.get_customer("CUST-003")) is RiskTier.HIGH
    assert policy.assess_return_risk(fixtures.get_customer("CUST-002")) is RiskTier.ELEVATED
    assert policy.assess_return_risk(fixtures.get_customer("CUST-001")) is RiskTier.LOW
