"""Thin wrapper around the Anthropic Messages API.

Kept deliberately small. One model call, no loop, no tool execution. The loop
lives in the orchestrator, which is the whole architectural point.

Note the SDK also ships client.beta.messages.tool_runner(), which runs the
agent loop and executes tools for you. We are not using it. Convenient in
production, useless for understanding what you are defending in an interview.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from anthropic import Anthropic, APIError

# One place to change this. The cost/latency/quality comparison exercise
# swaps only this constant.
MODEL = os.environ.get("RETURNS_AGENT_MODEL", "claude-sonnet-5")
MAX_TOKENS = 1024

_client: Optional[Anthropic] = None


def client() -> Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Put it in a .env file at the "
                "project root and make sure load_dotenv() has run."
            )
        _client = Anthropic()
    return _client


def call_model(
    system: str,
    messages: list[dict[str, Any]],
    tool_schemas: list[dict[str, Any]],
):
    """Single turn. Returns the raw Message object.

    Deliberately does not catch APIError -- the orchestrator decides what a
    failed model call means for the conversation. Swallowing it here would
    hide the decision.
    """
    return client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=messages,
        tools=tool_schemas,
    )
