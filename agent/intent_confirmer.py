# agent/intent_confirmer.py
"""
Intent Confirmer — Layer 1.5

Sits between IntentParser (Layer 1) and LogicalPlanBuilder (Layer 2).
Only activates when IntentParser returns 'unknown_intent' OR when the
caller explicitly requests confirmation (e.g. after a zero-results run).

Responsibilities:
- Show the LLM the classified intent + capability map
- Ask it to either confirm the intent bucket or reclassify
- Return a corrected intent dict with the same schema as IntentParser output
- Never block execution if LLM is unavailable — passes through unchanged

Does NOT replace IntentParser. IntentParser is always run first (deterministic,
zero latency). This only adds an LLM correction pass on top.

Slot in agent.answer():
    intent = self.intent_parser.parse(question)
    intent = self.intent_confirmer.confirm(question, intent)   ← Layer 1.5
    query_entry = self.plan_builder.build(intent)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, Any, Optional

from agent.llm_client import LLMClient
from agent.schema_context import CAPABILITY_MAP

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Valid intent types — must stay in sync with IntentParser._classify_intent
# ---------------------------------------------------------------------------

VALID_INTENT_TYPES = frozenset({
    "engineering_inventory",
    "valve_placement",
    "instrument_attachment",
    "line_attributes",
    "connectivity_topology",
    "flow_direction",
    "engineering_correctness",  # Phase 8 — topology-based P&ID conformance checks
    "flow_coverage",        # Phase 8 — analysis completeness, not drawing defects
    "external_interfaces",
    "redundancy_patterns",
    "drawing_consistency",
    "isolation_reachability",
    "annotation_requests",
    "segment_junction_topology",
    "cross_domain",         # Phase 8 — multi-domain joins, annotation triage
    "custom_query",
    "unknown_intent",
})


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def _build_system_prompt() -> str:
    cap_lines = []
    for intent, info in CAPABILITY_MAP.items():
        cap_lines.append(f'  "{intent}": {info["description"]}')

    return (
        "You are an intent classifier for a P&ID (Piping and Instrumentation "
        "Diagram) graph query system.\n\n"
        "You will receive:\n"
        "  1. A user question about a P&ID drawing\n"
        "  2. The intent type that was automatically classified by a keyword parser\n\n"
        "Your job: confirm whether the classified intent is correct, or return a better one.\n\n"
        "AVAILABLE INTENT TYPES:\n"
        + "\n".join(cap_lines)
        + "\n\n"
        "IMPORTANT CONTEXT ABOUT THIS GRAPH:\n"
        "- No OCR tag names (like CND-PU-163) exist — identity is by symbol type and position\n"
        "- Node.label is the symbol CLASS: tank | valve | instrumentation | general | "
        "arrow | crossing | inlet/outlet | connector | background\n"
        "- External interfaces are nodes with label='inlet/outlet', NOT structural_type='BOUNDARY'\n"
        "- Flow direction lives on LogicalPipeSegment via Arrow nodes\n"
        "- Quality/consistency issues: dangling ends, disconnected segments, orphaned annotations\n"
        "- flow_coverage = analysis COMPLETENESS (how many pipe lines have a resolved flow "
        "direction). NOT a drawing defect. Use for 'coverage', 'percentage resolved', "
        "'missing direction on pipe lines'.\n"
        "- cross_domain = questions joining multiple symbol types OR annotation triage metadata "
        "(ESV, KAV, severity, hitl, priority, critical issues). Also use when a quality word "
        "modifies a specific equipment type, e.g. 'valves with flow problems'.\n"
        "- drawing_consistency = standalone defect/quality questions with no specific equipment "
        "subject — e.g. 'are there orphaned symbols?', 'show drawing issues'.\n\n"
        "RULES:\n"
        "- Respond ONLY with a valid JSON object\n"
        "- No explanation, no markdown, no preamble\n"
        "- Always include all fields shown in the output schema\n"
        "- If the classified intent is correct, return it unchanged\n"
        "- If you reclassify, explain briefly in the 'reason' field\n\n"
        'OUTPUT SCHEMA (respond with exactly this structure):\n'
        "{\n"
        '  "intent_type": "<one of the valid intent types above>",\n'
        '  "confidence": "high" | "medium" | "low",\n'
        '  "reason": "<one sentence — why this intent, or why you changed it>",\n'
        '  "operation": "count" | "list" | "path" | null\n'
        "}"
    )


_SYSTEM_PROMPT: str = _build_system_prompt()


# ---------------------------------------------------------------------------
# Intent Confirmer
# ---------------------------------------------------------------------------

class IntentConfirmer:
    """
    LLM-powered intent correction layer.

    Behaviour:
    - If classified intent is unknown_intent → always call LLM to reclassify
    - If classified intent is known and confirm_unknown_only=True → no-op
    - If LLM unavailable or fails → return original intent unchanged
    - If LLM returns invalid intent type → return original intent unchanged

    Thread-safe: stateless, no shared mutable state.
    Pylance-safe: _llm is narrowed to non-None before every call site.
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient],
        *,
        confirm_unknown_only: bool = False,
    ) -> None:
        """
        Args:
            llm_client: LLM client. If None, confirmer is a transparent
                pass-through — zero overhead, zero latency.
            confirm_unknown_only: If False (default), call LLM for every query
                so misclassifications are caught before Cypher generation.
                If True, only call LLM when IntentParser returned 'unknown_intent'
                (lower accuracy, lower latency — use only if LLM calls are expensive).
        """
        # Store as private; type is Optional so callers don't need to guard.
        # We narrow to non-None at every internal call site.
        self._llm: Optional[LLMClient] = llm_client
        self._confirm_unknown_only = confirm_unknown_only

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def confirm(
        self,
        question: str,
        intent: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Confirm or correct the intent dict produced by IntentParser.

        Always returns a valid intent dict with the same schema.
        Never raises — on any failure returns the original intent unchanged.
        """
        # ── Fast-path: no LLM configured ──
        if self._llm is None:
            return intent

        classified = intent.get("intent_type", "unknown_intent")

        # ── Fast-path: known intent + unknown-only mode ──
        if self._confirm_unknown_only and classified != "unknown_intent":
            return intent

        # ── LLM call ── (self._llm is non-None here, narrowed by the guard above)
        try:
            return self._call_llm(question, intent)
        except BaseException as exc:
            logger.warning(
                f"[IntentConfirmer] LLM call failed ({exc}) — keeping parser result"
            )
            return intent

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call_llm(
        self,
        question: str,
        intent: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Call the LLM, parse the response, merge into intent.
        Caller guarantees self._llm is not None before calling this.
        """
        # Narrow type for Pylance: we know _llm is non-None here because
        # confirm() guards on it before calling _call_llm.
        llm: LLMClient = self._llm  # type: ignore[assignment]
        # The type: ignore above is safe — confirm() only reaches _call_llm
        # when self._llm is not None. We re-check here to be explicit:
        if llm is None:
            return intent

        classified = intent.get("intent_type", "unknown_intent")
        keywords   = intent.get("keywords", [])
        slots      = intent.get("slots", {})

        message = (
            f"User question: {question}\n"
            f"Classified intent: {classified}\n"
            f"Keywords detected: {keywords}\n"
            f"Slots extracted: {json.dumps(slots)}\n\n"
            "Is this classification correct? "
            "If not, return the better intent type."
        )

        raw = llm.complete(
            system     = _SYSTEM_PROMPT,
            message    = message,
            max_tokens = 150,
        )

        parsed = self._parse_response(raw)
        if parsed is None:
            return intent

        new_intent_type = parsed.get("intent_type", classified)

        # Validate — never accept a hallucinated intent type
        if new_intent_type not in VALID_INTENT_TYPES:
            logger.warning(
                f"[IntentConfirmer] LLM returned unknown intent type "
                f"'{new_intent_type}' — keeping '{classified}'"
            )
            return intent

        if new_intent_type != classified:
            logger.info(
                f"[IntentConfirmer] Reclassified '{classified}' → "
                f"'{new_intent_type}' reason: {parsed.get('reason', '—')}"
            )

        # Merge: keep all original fields, update intent_type + add metadata
        corrected = dict(intent)
        corrected["intent_type"] = new_intent_type
        corrected["_confirmer"]  = {
            "original_intent": classified,
            "confidence":      parsed.get("confidence", "medium"),
            "reason":          parsed.get("reason", ""),
        }

        # Override operation hint if LLM detected a different one AND the
        # keyword parser didn't already produce a strong count/path signal
        llm_op = parsed.get("operation")
        if llm_op and llm_op in ("count", "list", "path"):
            existing_kw     = set(corrected.get("keywords", []))
            has_strong_count = bool(existing_kw & {"how", "many", "count", "total"})
            if not has_strong_count:
                corrected["_llm_operation"] = llm_op

        return corrected

    @staticmethod
    def _parse_response(raw: str) -> Optional[Dict[str, Any]]:
        """
        Parse LLM JSON response.
        Returns None on any parse failure so the caller falls back gracefully.
        """
        if not raw:
            return None

        text = raw.strip()

        # Strip markdown fences if the LLM wrapped the JSON
        if text.startswith("```"):
            text = "\n".join(
                line for line in text.splitlines()
                if not line.strip().startswith("```")
            ).strip()

        # Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Fallback: extract first JSON object from the response
        match = re.search(r"\{[^{}]+\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        logger.debug(
            f"[IntentConfirmer] Could not parse LLM response: {raw[:200]}"
        )
        return None