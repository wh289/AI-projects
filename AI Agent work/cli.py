"""Headless driver. Same orchestrator the web UI will call later.

    python cli.py                 interactive
    python cli.py --customer CUST-002

Shows every tool call and outcome inline. Keep it that way -- an agent you
cannot watch is an agent you cannot debug, and this view is also what you
would demo to an interviewer.
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from core import fixtures, orchestrator  # noqa: E402

GREY = "\033[90m"
CYAN = "\033[96m"
RED = "\033[91m"
RESET = "\033[0m"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer", default="CUST-001")
    args = parser.parse_args()

    customer = fixtures.get_customer(args.customer)
    if customer is None:
        print(f"Unknown customer {args.customer}. Try: {', '.join(fixtures.CUSTOMERS)}")
        return 1

    state = orchestrator.new_conversation(customer.customer_id)
    print(f"{GREY}Session for {customer.name} ({customer.customer_id}). "
          f"Orders: {', '.join(o.order_id for o in fixtures.orders_for_customer(customer.customer_id))}")
    print(f"Ctrl-C to quit.{RESET}\n")

    while True:
        try:
            utterance = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not utterance:
            continue

        result = orchestrator.run_turn(state, utterance)

        for call, outcome in zip(result.tool_calls, result.tool_outcomes):
            colour = GREY if outcome.ok else RED
            flag = "" if outcome.ok else f" [{outcome.error_code}]"
            replay = " (replayed)" if outcome.replayed else ""
            print(f"{colour}  · {call.name}({call.arguments}){flag}{replay}{RESET}")

        print(f"\n{CYAN}agent >{RESET} {result.reply}\n")
        if result.stopped_reason != "completed":
            print(f"{GREY}  [stopped: {result.stopped_reason}]{RESET}\n")


if __name__ == "__main__":
    sys.exit(main())
