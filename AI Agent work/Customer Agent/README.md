# Returns Agent

A single agent with a rich tool layer, handling customer returns. Built so the
orchestrator is a library that a UI and an eval harness can both drive.

The architectural claim this codebase exists to demonstrate: **the orchestrator
owns the loop and enforces deterministic policy; the model proposes but does
not decide or execute.**

---

## Setup (Windows / PowerShell)

```powershell
cd returns-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then create your `.env` from the template:

```powershell
Copy-Item .env.example .env
notepad .env
```

Tests need no API key. Only `cli.py` does.

```powershell
pytest -v
python cli.py
```

In VS Code, `Ctrl+Shift+P` → *Python: Select Interpreter* → pick `.venv`, so
the test explorer picks up the gaps.

---

## Layout

```
core/
  models.py        types, incl. the Claim schema      COMPLETE
  fixtures.py      fake orders and customers          COMPLETE
  policy.py        deterministic rules                GAPS 1, 2
  tools.py         schemas + handlers                 COMPLETE
  action_layer.py  executor + gatekeeper              GAP 3
  llm.py           one model call, nothing else       COMPLETE
  prompt.py        system prompt + turn wrapping      COMPLETE
  orchestrator.py  the loop                           GAP 4
tests/             the contract for every gap
cli.py             headless driver
```

Read `models.Claim` first. It encodes the distinction the rest of the design
rests on: the model emits what the customer *asserted*, never a determination
about a physical object it has never seen.

---

## The gaps, in order

Each has a docstring spec and failing tests. Do them in this order — later
tests depend on earlier gaps.

| # | Where | What | Test file |
|---|-------|------|-----------|
| 1 | `policy.compute_refund` | Refund arithmetic and its explanation | `test_policy.py` |
| 3 | `action_layer.execute` | Validate, authorise, dedupe, run, catch | `test_action_layer.py` |
| 4 | `orchestrator.run_turn` | The loop | `test_orchestrator.py` |
| 2 | `policy.escalation_required` | Mandatory vs requested escalation | `test_policy.py` |

Gap 2 is numbered second in the file but attempt it last — it makes most sense
once you have seen how the loop consumes policy output.

Run one gap's tests at a time:

```powershell
pytest tests/test_action_layer.py -v
```

---

## Questions the code asks you

Each of these is written into a docstring at the point where it bites. They
are the parts an interviewer would push on.

- Why must a non-existent order and another customer's order be
  indistinguishable in the response?
- Why does the loop terminate on the absence of tool calls rather than on
  `stop_reason == "end_turn"`?
- Why is `risk_tier` passed into `compute_refund` but forbidden from changing
  the amount?
- Why is the escalation asymmetry — model can request, cannot suppress —
  enforced in code rather than in the system prompt?

---

## Deliberately not used

`client.beta.messages.tool_runner()` in the Anthropic SDK runs this loop for
you and executes tools automatically. It is the right call in production and
the wrong one here: the loop is the thing you need to be able to defend.

Same reasoning for LangGraph. Port to it *after* this works, as a second
exercise, so the comparison is grounded in something you built by hand.

---

## Next, once the gaps are closed

1. `web/` — thin React UI, renders tool calls visibly so the machinery shows.
2. `evals/` — the fake model in `test_orchestrator.py` is already the seed.
   Extend to scored conversations: tool-choice correctness deterministically,
   tone and resolution quality by judge.
3. Failure injection — prompt injection through `record_customer_claim`,
   handler timeouts, a customer who confidently asserts a false policy.
