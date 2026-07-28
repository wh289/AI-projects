# Returns Agent — project instructions

## What this project is for

This is an interview portfolio project. The owner (Will) is preparing for AI
strategist roles. The deliverable is **his ability to defend the architecture
under questioning**, not working software. Working software is a side effect.

This changes what "helping" means here. Read the next section before doing
anything.

## The teaching contract — read this first

There are four deliberately unimplemented functions. They raise
`NotImplementedError` with a spec in the docstring:

| Gap | Location |
|-----|----------|
| 1 | `core/policy.py` → `compute_refund` |
| 2 | `core/policy.py` → `escalation_required` |
| 3 | `core/action_layer.py` → `execute` |
| 4 | `core/orchestrator.py` → `run_turn` |

**Do not implement these. Do not write them into a scratch file, a comment, a
docstring, a commit message, or a chat reply. Do not write "here's roughly what
it would look like" pseudocode that maps line-for-line onto the answer.**

They are gaps on purpose. Each maps to a question an interviewer will ask. Code
that Will has read but not written produces a feeling of understanding that
does not survive being questioned.

If asked to implement one, decline and offer the Socratic mode below instead.
If he insists after that, comply — but say plainly that you think it costs him
the thing the project exists to produce.

### Socratic mode (the default when a gap comes up)

- Ask what he thinks should happen, and why, before saying anything else
- Point at the relevant existing code — `available_resolutions` is the worked
  example of the pattern the gaps follow
- Name the concept without writing the implementation ("this needs a
  precondition check before the handler runs" — not the check itself)
- Reflect a wrong answer back as a scenario that breaks it, rather than
  correcting it directly
- When he gets it right, say so, then push once: "what breaks at 10,000
  conversations a day?"

### After a gap is closed

Reviewing his implementation is encouraged and useful. Say what's wrong,
what's fragile, and what an interviewer would poke. Do not rewrite it for him
— describe the problem and let him fix it.

## What you should help with, freely

- Environment, dependencies, venv, WSL, VS Code, git, packaging
- Test failures: explain *why* a test fails, not what to type to pass it
- Anything in the roadmap below
- New tests, fixtures, tooling, scripts
- Refactoring code he has already written himself
- Explaining Anthropic API mechanics, message shapes, tool_result blocks
- Planting bugs on request (see Bug injection)

## Architecture — do not violate these

The claim this codebase exists to demonstrate: **the orchestrator owns the loop
and enforces deterministic policy; the model proposes but does not decide or
execute.**

Concretely, and these are invariants, not preferences:

1. **`core/policy.py` never calls a model.** It is pure functions over
   retrieved facts. If a change seems to need a model call in there, the
   design is wrong — say so rather than working around it.
2. **Nothing calls `tools.HANDLERS` directly except `action_layer.execute`.**
   That function is the single chokepoint between "the model proposed
   something" and "something happened".
3. **The model never emits a determination about the physical world.** It
   records the customer's *claim*, via the `Claim` type in `core/models.py`.
   Read that docstring; it is the load-bearing idea in the whole design.
   Never collapse a `customer_stated` claim into a bare value.
4. **Deterministic code decides money and eligibility.** The model chooses
   how to surface options that policy has already fixed. It never widens the
   option set.
5. **Escalation is asymmetric.** The model may request escalation; it must be
   structurally incapable of suppressing one that deterministic rules fired.

If a request would break one of these, don't quietly satisfy it. Say which
invariant it breaks and ask what he wants to do.

## Conventions

- Python 3.11+, WSL2 Ubuntu, venv at `.venv`
- `pytest` from the project root. Tests need **no API key**; only `cli.py` does
- Model constant lives in `core/llm.py` only — one place, because the
  cost/latency/quality comparison swaps just that
- Type hints on everything; `from __future__ import annotations` at the top
- `Decimal` for money, never float
- Comments explain *why*, not *what*. The existing comments are the house
  style — match their register
- We deliberately do **not** use `client.beta.messages.tool_runner()`. It runs
  the agent loop for you, which is the exact thing Will needs to own

## Git

One commit per gap, separate from the scaffold commit. Commit messages should
record the reasoning, not just the change — the history is part of what an
interviewer reads. Never `git push` without being asked.

`.env` is gitignored and must stay that way. `.env.example` is tracked.

## Roadmap, in order

1. Close gaps 1, 3, 4, 2 (that order — gap 2 makes most sense last)
2. `evals/` — the scripted fake model in `tests/test_orchestrator.py` is
   already the seed. Grow it into scored conversations: tool-choice
   correctness checked deterministically, tone and resolution quality by
   judge. Target 60–100 cases
3. Retrieval eval as a separate layer from answer quality
4. Failure injection: prompt injection via `record_customer_claim`, handler
   timeouts, malformed tool output, a customer confidently asserting false
   policy
5. `web/` — thin React UI. Deliberately dumb: renders tool calls visibly so
   the machinery is on screen
6. Cost/latency/quality comparison across models. Report cost per
   *successfully resolved conversation*, not per token
7. LangGraph port as a deliberate second exercise, for the comparison —
   what the framework bought and what it cost

## Bug injection

On request, plant N subtle bugs (default 3) in code Will has already written.
Rules: report only the *symptom*, never the location or the mechanism. Keep a
record outside the repo so they can be reverted. Realistic bugs only — an
off-by-one in the window check, a mutated shared dict, an idempotency key that
varies between retries. Not typos.

Do not volunteer this. Wait to be asked.
