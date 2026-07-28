"""Core data types.

The most important type here is Claim. Read its docstring before anything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Optional

# --------------------------------------------------------------------------
# Claims vs facts
# --------------------------------------------------------------------------

ClaimSource = Literal["customer_stated", "system_verified"]


@dataclass(frozen=True)
class Claim:
    """An assertion about the world, tagged with where it came from.

    This exists because of a specific failure mode. If a customer says
    "the item is unused", the model has no access to the item -- it is a
    physical object in someone's hallway. The model is being asked to
    adjudicate a claim about the world using the claim itself as its only
    evidence. That is circular, and it means a persuasive customer gets a
    different outcome than an inarticulate one for an identical item.

    So the model never emits a determination about the physical world.
    It emits the customer's CLAIM, tagged as a claim. Deterministic policy
    then decides what an unverified claim entitles the customer to.

    Never collapse a customer_stated claim into a bare value elsewhere in
    the codebase. The source tag is load-bearing.
    """

    attribute: str  # e.g. "condition", "reason_code", "packaging_intact"
    value: str  # e.g. "unused"
    source: ClaimSource
    utterance: Optional[str]  # the raw customer text this came from
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_verified(self) -> bool:
        return self.source == "system_verified"


# --------------------------------------------------------------------------
# Domain enums
# --------------------------------------------------------------------------


class RiskTier(str, Enum):
    LOW = "low"
    ELEVATED = "elevated"
    HIGH = "high"


class ResolutionType(str, Enum):
    REFUND_ORIGINAL_PAYMENT = "refund_original_payment"
    STORE_CREDIT = "store_credit"
    EXCHANGE_SAME_ITEM = "exchange_same_item"
    REPAIR = "repair"


class ReasonCode(str, Enum):
    DOESNT_FIT = "doesnt_fit"
    NOT_AS_DESCRIBED = "not_as_described"
    ARRIVED_DAMAGED = "arrived_damaged"
    CHANGED_MIND = "changed_mind"
    WRONG_ITEM_SENT = "wrong_item_sent"
    FAULTY = "faulty"


# --------------------------------------------------------------------------
# Fixtures / catalogue types
# --------------------------------------------------------------------------


@dataclass
class OrderItem:
    item_id: str
    sku: str
    name: str
    category: str
    unit_price: Decimal
    quantity: int
    final_sale: bool = False


@dataclass
class Order:
    order_id: str
    customer_id: str
    placed_at: datetime
    delivered_at: Optional[datetime]
    items: list[OrderItem]

    def item(self, item_id: str) -> Optional[OrderItem]:
        return next((i for i in self.items if i.item_id == item_id), None)


@dataclass
class Customer:
    customer_id: str
    name: str
    tier: Literal["standard", "plus"]
    returns_last_90_days: int
    lifetime_orders: int
    fraud_flag: bool = False


# --------------------------------------------------------------------------
# Policy outputs
# --------------------------------------------------------------------------


@dataclass
class WindowCheck:
    within_window: bool
    days_elapsed: Optional[int]
    window_days: int
    reason: str


@dataclass
class RefundBreakdown:
    gross: Decimal
    restocking_fee: Decimal
    shipping_refunded: Decimal
    net: Decimal
    currency: str = "GBP"
    notes: list[str] = field(default_factory=list)


@dataclass
class Resolution:
    type: ResolutionType
    label: str
    requires_inspection: bool
    estimated_value: Decimal


@dataclass
class EscalationTrigger:
    code: str
    detail: str
    mandatory: bool  # True = deterministic rule fired; the model cannot override


# --------------------------------------------------------------------------
# Action layer types
# --------------------------------------------------------------------------


@dataclass
class ToolCall:
    """A tool invocation REQUESTED by the model. Not yet executed."""

    tool_use_id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolOutcome:
    """The result of putting a ToolCall through the action layer."""

    tool_use_id: str
    ok: bool
    payload: dict[str, Any]
    error_code: Optional[str] = None
    replayed: bool = False  # True if served from the idempotency cache


# --------------------------------------------------------------------------
# Conversation state
# --------------------------------------------------------------------------


@dataclass
class ConversationState:
    conversation_id: str
    customer_id: str

    # API-shaped message list. The orchestrator owns this; nothing else writes to it.
    messages: list[dict[str, Any]] = field(default_factory=list)

    # Everything the model has asserted or been told, kept separately from the
    # transcript so policy can read it without parsing prose.
    claims: list[Claim] = field(default_factory=list)
    verified_facts: dict[str, Any] = field(default_factory=dict)

    # Gatekeeping bookkeeping
    tools_called: list[str] = field(default_factory=list)
    idempotency_cache: dict[str, ToolOutcome] = field(default_factory=dict)

    escalated: bool = False
    escalation_reason: Optional[str] = None
    turn_count: int = 0

    def add_claim(self, claim: Claim) -> None:
        self.claims.append(claim)

    def latest_claim(self, attribute: str) -> Optional[Claim]:
        matches = [c for c in self.claims if c.attribute == attribute]
        return matches[-1] if matches else None

    def has_called(self, tool_name: str) -> bool:
        return tool_name in self.tools_called
