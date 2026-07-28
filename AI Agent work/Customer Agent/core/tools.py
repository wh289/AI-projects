"""Tool registry.

Two things live here and they are worth keeping distinct in your head:

  1. SCHEMAS -- what the model is told exists. This is part of the prompt.
  2. HANDLERS -- what actually runs. The model never touches these.

The handlers are plain functions with no notion of a model. You can call
every one of them from a test without an API key. If a handler ever needs
to know it was invoked by an LLM, something has leaked.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from . import fixtures, policy
from .models import Claim, ConversationState, ReasonCode, ResolutionType

# --------------------------------------------------------------------------
# Schemas exposed to the model
# --------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "lookup_order",
        "description": (
            "Retrieve an order and its items. Call this before discussing any "
            "specifics of an order. Returns items, prices and delivery date."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "e.g. ORD-1001"},
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "record_customer_claim",
        "description": (
            "Record something the customer has asserted that cannot be verified "
            "from systems -- the condition of the item, whether packaging is "
            "intact, why they are returning it. This records the assertion only. "
            "It does not establish the assertion as true and does not by itself "
            "entitle the customer to anything."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "attribute": {
                    "type": "string",
                    "enum": ["condition", "packaging_intact", "reason_code", "item_received"],
                },
                "value": {"type": "string"},
                "utterance": {
                    "type": "string",
                    "description": "The customer's own words that this was drawn from.",
                },
            },
            "required": ["attribute", "value", "utterance"],
        },
    },
    {
        "name": "get_return_eligibility",
        "description": (
            "Ask the returns policy engine whether an item can be returned and "
            "what the customer would receive. You must call this before stating "
            "any figure or making any offer. Never calculate a refund yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "item_id": {"type": "string"},
                "reason_code": {
                    "type": "string",
                    "enum": [r.value for r in ReasonCode],
                },
            },
            "required": ["order_id", "item_id", "reason_code"],
        },
    },
    {
        "name": "initiate_return",
        "description": (
            "Actually start the return. This moves money and generates a label. "
            "Only call this after get_return_eligibility has returned the chosen "
            "resolution as available, and only after the customer has explicitly "
            "confirmed which option they want."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "item_id": {"type": "string"},
                "resolution_type": {
                    "type": "string",
                    "enum": [r.value for r in ResolutionType],
                },
                "idempotency_key": {
                    "type": "string",
                    "description": (
                        "Stable key for this specific return request. Reuse the "
                        "same key if retrying; do not generate a new one."
                    ),
                },
            },
            "required": ["order_id", "item_id", "resolution_type", "idempotency_key"],
        },
    },
    {
        "name": "request_escalation",
        "description": (
            "Hand the conversation to a human agent. Use when the customer asks "
            "for a human, when you cannot resolve the issue, or when the customer "
            "is distressed. Requesting escalation is always permitted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
            },
            "required": ["reason"],
        },
    },
]

# Tools that change the world. The action layer treats these differently.
MUTATING_TOOLS = {"initiate_return", "request_escalation"}

# Preconditions: tool name -> tools that must already have run this conversation.
TOOL_PRECONDITIONS: dict[str, set[str]] = {
    "get_return_eligibility": {"lookup_order"},
    "initiate_return": {"lookup_order", "get_return_eligibility"},
}


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------


def _serialise(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_serialise(o) for o in obj]
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        return _serialise(asdict(obj))
    if hasattr(obj, "value"):  # Enum
        return obj.value
    return obj


def handle_lookup_order(args: dict[str, Any], state: ConversationState) -> dict[str, Any]:
    order = fixtures.get_order(args["order_id"])
    if order is None:
        return {"found": False, "message": "No order with that reference."}
    if order.customer_id != state.customer_id:
        # Authorisation is enforced again in the action layer; this is defence
        # in depth, not redundancy.
        return {"found": False, "message": "No order with that reference."}

    state.verified_facts["order_id"] = order.order_id
    return {"found": True, "order": _serialise(order)}


def handle_record_customer_claim(args: dict[str, Any], state: ConversationState) -> dict[str, Any]:
    claim = Claim(
        attribute=args["attribute"],
        value=args["value"],
        source="customer_stated",
        utterance=args["utterance"],
    )
    state.add_claim(claim)
    return {
        "recorded": True,
        "attribute": claim.attribute,
        "value": claim.value,
        "status": "unverified_customer_assertion",
        "note": (
            "Recorded as an assertion by the customer. It has not been verified "
            "and does not establish eligibility on its own."
        ),
    }


def handle_get_return_eligibility(args: dict[str, Any], state: ConversationState) -> dict[str, Any]:
    order = fixtures.get_order(args["order_id"])
    customer = fixtures.get_customer(state.customer_id)
    if order is None or customer is None:
        return {"eligible": False, "message": "Order not found."}
    item = order.item(args["item_id"])
    if item is None:
        return {"eligible": False, "message": "Item not found on that order."}

    window = policy.check_return_window(order, item, customer)
    risk = policy.assess_return_risk(customer)
    options = policy.available_resolutions(order, item, customer, args["reason_code"])
    refund = policy.compute_refund(item, args["reason_code"], risk, item.quantity)

    state.verified_facts["eligibility_checked_for"] = f"{order.order_id}/{item.item_id}"

    return {
        "eligible": bool(options),
        "window": _serialise(window),
        "resolution_options": _serialise(options),
        "refund_if_refunded": _serialise(refund),
        "final_sale": item.final_sale,
        "policy_note": (
            "resolution_options is exhaustive. Do not offer anything absent "
            "from this list, and do not restate figures other than those given here."
        ),
    }


def handle_initiate_return(args: dict[str, Any], state: ConversationState) -> dict[str, Any]:
    order = fixtures.get_order(args["order_id"])
    if order is None:
        return {"created": False, "message": "Order not found."}
    rma = f"RMA-{order.order_id[-4:]}-{args['item_id']}"
    return {
        "created": True,
        "rma_number": rma,
        "resolution_type": args["resolution_type"],
        "return_label_url": f"https://example.invalid/labels/{rma}.pdf",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def handle_request_escalation(args: dict[str, Any], state: ConversationState) -> dict[str, Any]:
    state.escalated = True
    state.escalation_reason = args.get("reason", "model_requested")
    return {"escalated": True, "queue": "returns_tier_2", "wait_estimate_minutes": 6}


HANDLERS: dict[str, Callable[[dict[str, Any], ConversationState], dict[str, Any]]] = {
    "lookup_order": handle_lookup_order,
    "record_customer_claim": handle_record_customer_claim,
    "get_return_eligibility": handle_get_return_eligibility,
    "initiate_return": handle_initiate_return,
    "request_escalation": handle_request_escalation,
}
