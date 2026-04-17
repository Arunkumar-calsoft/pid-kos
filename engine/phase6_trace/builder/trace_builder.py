# phase6_trace/builder/trace_builder.py
"""
TraceBuilder — Phase-6 Reasoning Trace Constructor

Fixes applied vs original:
  1. Uses current_utc_time() from utils.time  (was: datetime.utcnow().isoformat())
       Before: "2026-02-18T14:20:00.123456"   — no Z, no timezone, deprecated in 3.12
       After:  "2026-02-18T14:20:00Z"          — ISO 8601, schema-compliant

  2. Uses generate_trace_id() from utils.trace_id  (was: str(uuid.uuid4()))
       Before: "f47ac10b-58cc-4372-a567-0e02b2c3d479"
       After:  "trace-f47ac10b-58cc-4372-a567-0e02b2c3d479"

  3. category validated against schema enum at construction time.
       Before: any string silently accepted — produced invalid traces
       After:  ValueError raised immediately on invalid category

  4. context sanitized at construction time — non-scalar values dropped.
       Schema: additionalProperties: {type: [string, number, boolean]}
       Before: Dict[str, object] stored lists, dicts, None — schema violation
       After:  only str/int/float/bool kept; rest dropped.
       Callers should pre-flatten context (see trace_adapter.py) — this
       sanitizer is a last-resort net, not a substitute for correct callers.
"""
from __future__ import annotations

from typing import Dict, List, Any, Optional, Union

from engine.phase6_trace.builder.trace_step import TraceStep
from engine.phase6_trace.utils.time import current_utc_time
from engine.phase6_trace.utils.trace_id import generate_trace_id


# ---------------------------------------------------------------------------
# Schema-locked category enum — mirrors trace_schema.json exactly
# ---------------------------------------------------------------------------

VALID_CATEGORIES = frozenset({
    "inventory",
    "topology",
    "lines",
    "instruments",
    "valves",
    "directionality",
    "redundancy",
    "external_interfaces",
    "reachability",
    "quality",
    # Phase 5 categories added to Phase 6 trace coverage
    "annotations",
    "cross_domain",
    "engineering_correctness",
    "equipment_semantics",
    "flow_coverage",
    "flow_nodes",
    "pipe_edges",
})

_ScalarValue = Union[str, int, float, bool]


# ---------------------------------------------------------------------------
# TraceBuilder
# ---------------------------------------------------------------------------

class TraceBuilder:
    """
    Constructs a Phase-6 reasoning trace compliant with trace_schema.json.

    Usage:
        builder = TraceBuilder(
            question_text = "How many valves are there?",
            category      = "valves",
            context       = {"pid_id": "PID-001", "intent_type": "valve_placement"},
            pid_id        = "PID-001",
            graph_version = "v1.2",
        )
        builder.add_step(step)
        builder.set_summary("28 valves found.", counts={"records": 28})
        trace_dict = builder.build()
    """

    def __init__(
        self,
        question_text: str,
        category:      str,
        context:       Dict[str, Any],
        pid_id:        str,
        graph_version: str,
        executed_by:   str = "system",
    ) -> None:

        if category not in VALID_CATEGORIES:
            raise ValueError(
                f"Invalid trace category '{category}'. "
                f"Must be one of: {sorted(VALID_CATEGORIES)}"
            )

        self.trace_id = generate_trace_id()
        self.phase    = 6

        self.question: Dict[str, str] = {
            "text":     question_text,
            "category": category,
        }

        self.context: Dict[str, _ScalarValue] = _sanitize_context(context)

        self.steps: List[TraceStep] = []

        self.provenance: Dict[str, str] = {
            "pid_id":        pid_id,
            "graph_version": graph_version,
            "executed_by":   executed_by,
        }

        self.started_at:   str           = current_utc_time()
        self.completed_at: Optional[str] = None

        self.summary_statement: Optional[str]              = None
        self.summary_counts:    Optional[Dict[str, float]] = None

    def add_step(self, step: TraceStep) -> None:
        self.steps.append(step)

    def set_summary(
        self,
        statement: str,
        counts:    Optional[Dict[str, float]] = None,
    ) -> None:
        self.summary_statement = statement
        self.summary_counts    = counts

    def build(self) -> Dict[str, Any]:
        """Finalise and return schema-compliant trace dict."""
        if not self.steps:
            raise ValueError("Trace must contain at least one step.")
        if not self.summary_statement:
            raise ValueError("Trace summary statement is required.")

        self.completed_at = current_utc_time()

        return {
            "trace_id": self.trace_id,
            "phase":    self.phase,
            "question": self.question,
            "context":  self.context,
            "steps":    [s.to_dict() for s in self.steps],
            "summary": {
                "statement": self.summary_statement,
                **({"counts": self.summary_counts} if self.summary_counts else {}),
            },
            "provenance": self.provenance,
            "timestamps": {
                "started_at":   self.started_at,
                "completed_at": self.completed_at,
            },
        }


# ---------------------------------------------------------------------------
# Context sanitizer
# ---------------------------------------------------------------------------

def _sanitize_context(raw: Dict[str, Any]) -> Dict[str, _ScalarValue]:
    """Keep only schema-allowed scalars. Drop lists, dicts, None."""
    return {
        k: v for k, v in raw.items()
        if isinstance(v, (str, int, float, bool))
    }