This is what engineers, reviewers, and auditors read.

Phase 6 — Reasoning Trace Schema (Explanation)
What this is

A reasoning trace records how a question about a P&ID graph was answered —
not guesses, not conclusions, not recommendations.

It is:

deterministic

replayable

auditable

read-only

What this is NOT

This schema does not:

infer process behavior

decide flow direction

judge safety or operability

modify the graph

Core Sections
question

The exact question asked, plus its structural category
(e.g. reachability, valves, quality).

context

All parameters used to specialize the question.

Example:

{
  "start_equipment": "CND-TK-160",
  "max_hops": 12
}

steps

An ordered log of what was executed.

Each step answers:

Why was this query run? → intent

Where did it come from? → source

What exactly ran? → query

With what inputs? → parameters

What came back? → result_stats

There is no interpretation here.

summary

A neutral, factual statement like:

“143 components are reachable from CND-TK-160 within 12 hops.”

This is not a conclusion, just an observation.

provenance

Allows full replay:

which P&ID

which graph build

who or what triggered it

timestamps

Start and end time for trace generation.

Used for:

audit

reproducibility

performance analysis

Hard Guarantees

No hidden fields (additionalProperties: false)

No free-form reasoning

No LLM opinions

No phase leakage

If it’s not in this schema, it doesn’t exist.

✅ Phase 6 Schema Status
Aspect	Status
Deterministic	✅
Read-only	✅
Engineer-auditable	✅
LLM-safe	✅
Phase-isolated	✅