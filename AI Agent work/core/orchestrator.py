"""The orchestrator. This file owns the loop.

The division of authority, stated once so it is not ambiguous anywhere else:
the orchestrator owns the loop and enforces deterministic policy; the model
proposes but does not decide or execute.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from anthropic import APIError

from . import action_layer, llm, prompt, tools
from .models import ConversationState, ToolCall, ToolOutcome

MAX_TOOL_ITERATIONS = 8


@dataclass
class TurnResult:
    """Everything that happened in one user turn. Built for the eval harness.

    The harness scores tool_calls as well as reply text -- most agent failures
    are wrong tool usage with fluent prose wrapped around them, and if you only
    score the prose you cannot see them.
    """

    reply: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_outcomes: list[ToolOutcome] = field(default_factory=list)
    iterations: int = 0
    stopped_reason: str = "completed"


def new_conversation(customer_id: str) -> ConversationState:
    return ConversationState(
        conversation_id=str(uuid.uuid4()),
        customer_id=customer_id,
    )


# --------------------------------------------------------------------------
# COMPLETE -- helper for Gap 4.
# --------------------------------------------------------------------------


def extract_tool_calls(message: Any) -> list[ToolCall]:
    """Pull tool_use blocks out of an API response."""
    calls = []
    for block in message.content:
        if getattr(block, "type", None) == "tool_use":
            calls.append(ToolCall(tool_use_id=block.id, name=block.name,
                                  arguments=dict(block.input)))
    return calls


def extract_text(message: Any) -> str:
    return "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    ).strip()


# --------------------------------------------------------------------------
# GAP 4 -- the loop. Do this last, after Gaps 1 and 3.
# --------------------------------------------------------------------------


def run_turn(state: ConversationState, utterance: str) -> TurnResult:
    """Process one customer message end to end.

    Structure:

    1. state.turn_count += 1
    2. Append prompt.build_user_turn(utterance) to state.messages.
       Note that you append the WRAPPED turn, not the raw string.
    3. Loop, at most MAX_TOOL_ITERATIONS times:
         a. system = prompt.build_system_prompt(state)
            Rebuild it every iteration. Claims recorded during this turn must
            be visible to the model on the next iteration of the same turn.
         b. message = llm.call_model(system, state.messages, tools.TOOL_SCHEMAS)
         c. Append the assistant message to state.messages.
            The API needs message.content, not the text -- preserving tool_use
            blocks is what lets the next call resolve them.
         d. calls = extract_tool_calls(message)
            If empty: the model has produced a final reply. Return it.
         e. For each call, action_layer.execute(call, state), collect outcomes.
         f. Append ONE user message whose content is the list of
            to_tool_result_block(outcome) for every outcome. All results from
            one assistant turn go in a single message.
         g. Continue.
    4. If you exhaust MAX_TOOL_ITERATIONS, do not return an empty reply. Set
       stopped_reason="iteration_limit" and return something the customer can
       act on. A silent agent is worse than an agent that admits it is stuck.

    Handle APIError from step (b): return a TurnResult with
    stopped_reason="model_error" and a graceful message. Do not let it raise.

    One thing to get right, and it is the reason this is a gap rather than
    boilerplate: the loop terminates on the ABSENCE of tool calls, not on
    stop_reason == "end_turn". Work out why those are not the same thing.
    """
    raise NotImplementedError("GAP 4")
