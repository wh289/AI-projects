"""Contract for GAP 3, the action layer. No API key needed.

    pytest tests/test_action_layer.py -v
"""

import pytest

from core import action_layer, tools
from core.models import ConversationState, ToolCall


def state_for(customer_id="CUST-001"):
    return ConversationState(conversation_id="test", customer_id=customer_id)


def call(name, args, uid="tu_1"):
    return ToolCall(tool_use_id=uid, name=name, arguments=args)


# --------------------------------------------------------------------------
# 1. Schema validation
# --------------------------------------------------------------------------


def test_missing_required_argument_is_rejected():
    out = action_layer.execute(call("lookup_order", {}), state_for())
    assert out.ok is False
    assert out.error_code == "invalid_arguments"


def test_bad_enum_value_is_rejected():
    s = state_for()
    action_layer.execute(call("lookup_order", {"order_id": "ORD-1001"}), s)
    out = action_layer.execute(
        call("get_return_eligibility",
             {"order_id": "ORD-1001", "item_id": "IT-1", "reason_code": "vibes"}), s)
    assert out.ok is False
    assert out.error_code == "invalid_arguments"


def test_rejection_tells_the_model_what_was_wrong():
    out = action_layer.execute(call("lookup_order", {}), state_for())
    blob = str(out.payload).lower()
    assert "order_id" in blob, "a generic error teaches the model nothing"


# --------------------------------------------------------------------------
# 2. Authorisation
# --------------------------------------------------------------------------


def test_precondition_blocks_out_of_order_calls():
    out = action_layer.execute(
        call("get_return_eligibility",
             {"order_id": "ORD-1001", "item_id": "IT-1", "reason_code": "doesnt_fit"}),
        state_for())
    assert out.ok is False
    assert out.error_code == "precondition_failed"


def test_cannot_touch_another_customers_order():
    s = state_for("CUST-001")
    out = action_layer.execute(call("lookup_order", {"order_id": "ORD-1003"}), s)
    assert out.ok is False
    assert out.error_code == "not_authorised"


def test_unauthorised_and_missing_look_identical():
    """Otherwise the error message is an order-enumeration oracle."""
    s = state_for("CUST-001")
    other = action_layer.execute(call("lookup_order", {"order_id": "ORD-1003"}), s)
    missing = action_layer.execute(call("lookup_order", {"order_id": "ORD-9999"}), s)
    a = action_layer.to_tool_result_block(other)
    b = action_layer.to_tool_result_block(missing)
    assert a["content"] == b["content"], "the model must not be able to tell these apart"


# --------------------------------------------------------------------------
# 3. Idempotency
# --------------------------------------------------------------------------


def _ready_state():
    s = state_for("CUST-001")
    action_layer.execute(call("lookup_order", {"order_id": "ORD-1001"}), s)
    action_layer.execute(
        call("get_return_eligibility",
             {"order_id": "ORD-1001", "item_id": "IT-1", "reason_code": "doesnt_fit"}), s)
    return s


def test_duplicate_key_does_not_execute_twice():
    s = _ready_state()
    args = {"order_id": "ORD-1001", "item_id": "IT-1",
            "resolution_type": "refund_original_payment", "idempotency_key": "k-1"}
    first = action_layer.execute(call("initiate_return", args, "tu_a"), s)
    second = action_layer.execute(call("initiate_return", args, "tu_b"), s)

    assert first.ok and second.ok
    assert second.replayed is True
    assert first.payload["rma_number"] == second.payload["rma_number"]


def test_replay_returns_the_callers_own_tool_use_id():
    """Otherwise the API cannot match the result to the call it answers."""
    s = _ready_state()
    args = {"order_id": "ORD-1001", "item_id": "IT-1",
            "resolution_type": "store_credit", "idempotency_key": "k-2"}
    action_layer.execute(call("initiate_return", args, "tu_a"), s)
    second = action_layer.execute(call("initiate_return", args, "tu_b"), s)
    assert second.tool_use_id == "tu_b"


def test_non_mutating_tools_are_not_cached():
    s = state_for()
    a = action_layer.execute(call("lookup_order", {"order_id": "ORD-1001"}), s)
    b = action_layer.execute(call("lookup_order", {"order_id": "ORD-1001"}), s)
    assert a.ok and b.ok
    assert b.replayed is False


# --------------------------------------------------------------------------
# 4/5. Execution and failure handling
# --------------------------------------------------------------------------


def test_handler_exception_becomes_a_structured_error(monkeypatch):
    def boom(args, state):
        raise RuntimeError("payments provider timed out")

    monkeypatch.setitem(tools.HANDLERS, "lookup_order", boom)
    out = action_layer.execute(call("lookup_order", {"order_id": "ORD-1001"}), state_for())
    assert out.ok is False
    assert out.error_code == "tool_failed"


def test_execute_never_raises(monkeypatch):
    def boom(args, state):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(tools.HANDLERS, "lookup_order", boom)
    action_layer.execute(call("lookup_order", {"order_id": "ORD-1001"}), state_for())


def test_successful_call_is_recorded_on_state():
    s = state_for()
    action_layer.execute(call("lookup_order", {"order_id": "ORD-1001"}), s)
    assert s.has_called("lookup_order")


def test_result_block_marks_errors_for_the_api():
    out = action_layer.execute(call("lookup_order", {}), state_for())
    block = action_layer.to_tool_result_block(out)
    assert block["type"] == "tool_result"
    assert block["is_error"] is True
