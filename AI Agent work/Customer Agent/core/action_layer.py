"""The action layer: executor plus gatekeeper.

Every tool call the model requests passes through execute(). Nothing else in
the system may call a handler directly. This is the single chokepoint between
"the model proposed something" and "something happened".

You defined this layer yourself as an executor plus gatekeeper wrapping every
tool with schema validation, authorisation, idempotency and failure handling.
This file is that definition turned into code.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from . import tools, fixtures
from .models import ConversationState, ToolCall, ToolOutcome


class ActionLayerError(Exception):
    pass


# --------------------------------------------------------------------------
# COMPLETE -- helper you will need in Gap 3.
# --------------------------------------------------------------------------


def validate_arguments(name: str, arguments: dict[str, Any]) -> Optional[str]:
    """Check arguments against the declared input_schema.

    Returns an error string, or None if valid. Intentionally hand-rolled and
    shallow (types, required, enum) rather than pulling in jsonschema, so you
    can see exactly what is being checked. Swap in jsonschema later if you like.
    """
    schema = next((t["input_schema"] for t in tools.TOOL_SCHEMAS if t["name"] == name), None)
    if schema is None:
        return f"Unknown tool '{name}'."

    props = schema.get("properties", {})
    required = schema.get("required", [])

    for key in required:
        if key not in arguments:
            return f"Missing required argument '{key}'."

    for key, value in arguments.items():
        if key not in props:
            return f"Unexpected argument '{key}'."
        spec = props[key]
        if spec.get("type") == "string" and not isinstance(value, str):
            return f"Argument '{key}' must be a string."
        if "enum" in spec and value not in spec["enum"]:
            return f"Argument '{key}' must be one of {spec['enum']}."

    return None


# --------------------------------------------------------------------------
# GAP 3 -- the core of this project. Do this after Gap 1.
# --------------------------------------------------------------------------


def execute(call: ToolCall, state: ConversationState) -> ToolOutcome:
    """Put a model-requested tool call through the gate, then run it.

    Implement these five stages in order. Order matters: do not run the
    handler and then check whether you were allowed to.

    1. SCHEMA VALIDATION
       Use validate_arguments(). On failure return a ToolOutcome with ok=False
       and error_code="invalid_arguments". Put the specific problem in the
       payload -- the model needs to be able to correct itself, and a generic
       "error" teaches it nothing.

    2. AUTHORISATION
       Two distinct checks, do not conflate them:
       (a) Sequencing -- tools.TOOL_PRECONDITIONS says which tools must
           already have run. Reject with error_code="precondition_failed".
       (b) Ownership -- for any tool taking order_id, confirm the order
           belongs to state.customer_id. Reject with error_code="not_authorised".
           A non-existent order and someone else's order must be
           INDISTINGUISHABLE to the model: same error_code, same payload.
           Log the difference internally if you like, but do not return it.
           Work out what an attacker could do with a distinguishable response
           before you decide this is over-engineering.

    3. IDEMPOTENCY
       Only applies to tools in tools.MUTATING_TOOLS. If the call carries an
       idempotency_key already present in state.idempotency_cache, return the
       cached outcome with replayed=True and DO NOT run the handler. Otherwise
       run it and cache the result under that key.

       The scenario this defends against: the model calls initiate_return, the
       response is slow, the loop retries, and the customer is refunded twice.
       This must be impossible by construction, not unlikely.

    4. EXECUTION
       Call tools.HANDLERS[call.name](call.arguments, state). Append the tool
       name to state.tools_called.

    5. FAILURE HANDLING
       Wrap step 4 in try/except. A handler that raises must never propagate
       out of this function -- return ok=False with error_code="tool_failed"
       and a payload the model can act on. An unhandled exception here kills
       the conversation; a structured error lets the agent apologise and
       offer an alternative.

    Return a ToolOutcome in every path. No exceptions escape this function.
    """
    # Stage 1: schema validation
    error = validate_arguments(call.name, call.arguments)
    if error is not None:
        return ToolOutcome(
            tool_use_id=call.tool_use_id,
            ok=False,
            payload={"error": error},
            error_code="invalid_arguments",
        )
    
    required = tools.TOOL_PRECONDITIONS.get(call.name,set())
    missing = required - set(state.tools_called)
    if missing:
        return ToolOutcome(
            tool_use_id=call.tool_use_id,
            ok=False,
            payload={"error": f"Call {sorted(missing)} before {call.name}."},
            error_code="precondition_failed",
        )
    
    if "order_id" in call.arguments:
        order = fixtures.get_order(call.arguments["order_id"])
        not_found = order is None       # True if order is None
        wrong_owner = order is not None and order.customer_id != state.customer_id      # True if order exists but order.customer_id != state.customer_id
        if not_found or wrong_owner:
            return ToolOutcome(
                tool_use_id=call.tool_use_id,
                ok=False,
                payload={"error": "Order not found"},   # must be IDENTICAL text whichever branch fired
                error_code="not_authorised",
            )
        
    if call.name in tools.MUTATING_TOOLS and "idempotency_key" in call.arguments:
        key = call.arguments["idempotency_key"]
        if key in state.idempotency_cache:
            cached = state.idempotency_cache[key]
            return ToolOutcome(
                tool_use_id=call.tool_use_id,      # the NEW call's id, not the cached one
                ok=cached.ok,
                payload=cached.payload,
                error_code=cached.error_code,
                replayed=True,
            )
        
    try:
        outcome = tools.HANDLERS[call.name](call.arguments, state)
        state.tools_called.append(call.name)
        result = ToolOutcome(
            tool_use_id=call.tool_use_id, 
            ok=True, 
            payload=outcome, 
        )

        if call.name in tools.MUTATING_TOOLS and "idempotency_key" in call.arguments:
            key = call.arguments["idempotency_key"]
            state.idempotency_cache[key] = result
        return result
    except Exception as e:
        return ToolOutcome(
            tool_use_id=call.tool_use_id, 
            ok=False, 
            payload={"error": str(e)}, 
            error_code="tool_failed"
        )


# --------------------------------------------------------------------------
# COMPLETE -- shaping outcomes back into API content blocks.
# --------------------------------------------------------------------------


def to_tool_result_block(outcome: ToolOutcome) -> dict[str, Any]:
    """Convert a ToolOutcome into the tool_result block the API expects."""
    payload = dict(outcome.payload)
    if outcome.error_code:
        payload["error_code"] = outcome.error_code
    if outcome.replayed:
        payload["note"] = "Already executed earlier in this conversation; not repeated."

    return {
        "type": "tool_result",
        "tool_use_id": outcome.tool_use_id,
        "content": json.dumps(payload, default=str),
        "is_error": not outcome.ok,
    }
