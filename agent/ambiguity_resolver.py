# agent/ambiguity_resolver.py
"""
Ambiguity Resolver — Layer 2.5

Sits between LogicalPlanBuilder (Layer 2) and the CLI user-prompt fallback.

When LogicalPlanBuilder raises AmbiguityError (multiple registry candidates
tied on score), this resolver asks the LLM to pick the best one instead of
immediately surfacing the choice to the engineer.

Only escalates to the user when:
  - LLM is unavailable
  - LLM confidence is "low" (genuinely ambiguous question)
  - LLM returns an index it can't map to a candidate
  - LLM call fails for any reason

=== UPDATED 17 MARCH 2026 ===
_parser now handles real output from openai/gpt-oss-120b (current Groq flagship):
- strips ```json
- extracts first valid JSON object even with extra text
- fixes the exact parse failure you just saw
"""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, Any, List, Optional

from agent.llm_client import LLMClient
from agent.query_registry import QueryEntry
from agent.schema_context import CAPABILITY_MAP

logger = logging.getLogger(__name__)

# Max candidates to show user if LLM escalates
_MAX_USER_CANDIDATES = 3

_SYSTEM_PROMPT = """
You are a query disambiguation assistant for a P&ID (Piping and Instrumentation Diagram) graph database.

The user asked a question that matched multiple possible queries. Your job is to pick the single best query
based on the question's intent.

ABOUT THIS GRAPH:
- Nodes: valves, tanks, instruments, pipe segments, arrows, crossings, connectors, inlet/outlet points
- PIPE is the adjacency relationship between nodes
- LogicalPipeSegment represents a semantic stretch of pipe with flow direction
- PipeSegment is the raw physical geometry
- Connectivity = which nodes/segments are physically linked via PIPE edges
- "are all pipes connected?" → likely asking about drawing consistency / orphaned segments
- "is everything connected?" → same — connectivity or quality check
- "which lines branch?" → segment topology / junction query
- Quality/consistency checks include: orphan nodes, disconnected segments, missing flow

RULES:
- Respond ONLY with a valid JSON object, no markdown, no preamble
- Choose the single best match index (0-based)
- confidence: "high" if obvious, "medium" if reasonable, "low" if genuinely unclear

OUTPUT SCHEMA:
{
  "best_index": <integer 0-based>,
  "confidence": "high" | "medium" | "low",
  "reason": "<one sentence why>"
}
""".strip()


def _build_message(
    question:   str,
    intent:     Dict[str, Any],
    candidates: List[QueryEntry],
) -> str:
    intent_type = intent.get("intent_type", "unknown")
    keywords    = intent.get("keywords", [])

    cap = CAPABILITY_MAP.get(intent_type, {})
    cap_desc = cap.get("description", "")

    lines = [
        f"User question: {question}",
        f"Detected intent: {intent_type}",
        f"Intent description: {cap_desc}",
        f"Keywords detected: {keywords}",
        "",
        "Candidate queries (pick the best one):",
    ]
    for i, c in enumerate(candidates):
        title    = c.get("title", c.get("id", f"option {i}"))
        engineer = c.get("engineer_question", "")
        op       = c.get("operation", "")
        hint     = f" [{op}]" if op else ""
        eq_hint  = f" — e.g. '{engineer}'" if engineer else ""
        lines.append(f"  {i}: {title}{hint}{eq_hint}")

    return "\n".join(lines)


class AmbiguityResolver:
    """
    LLM-powered automatic disambiguation of tied registry candidates.

    Usage:
        resolver = AmbiguityResolver(llm_client)
        result = resolver.resolve(question, intent, candidates)
        if result.resolved:
            # auto-picked — no user prompt needed
            use result.query_entry
        else:
            # escalate to user with result.remaining_candidates (≤3)
            present result.remaining_candidates to user
    """

    def __init__(self, llm_client: Optional[LLMClient]) -> None:
        self._llm = llm_client

    def resolve(
        self,
        question:   str,
        intent:     Dict[str, Any],
        candidates: List[QueryEntry],
    ) -> "ResolverResult":
        """
        Try to auto-resolve ambiguity.

        Returns ResolverResult with:
          resolved=True  → query_entry is the auto-picked choice (no user prompt)
          resolved=False → remaining_candidates is a trimmed list (≤3) to show user
        """
        # Fast-path: no LLM
        if self._llm is None:
            return ResolverResult(
                resolved            = False,
                remaining_candidates= candidates[:_MAX_USER_CANDIDATES],
            )

        try:
            return self._call_llm(question, intent, candidates)
        except BaseException as exc:
            logger.warning(f"[AmbiguityResolver] LLM call failed ({exc}) — escalating to user")
            return ResolverResult(
                resolved             = False,
                remaining_candidates = candidates[:_MAX_USER_CANDIDATES],
            )

    def _call_llm(
        self,
        question:   str,
        intent:     Dict[str, Any],
        candidates: List[QueryEntry],
    ) -> "ResolverResult":
        assert self._llm is not None
        message = _build_message(question, intent, candidates)

        raw = self._llm.complete(
            system     = _SYSTEM_PROMPT,
            message    = message,
            max_tokens = 120,
        )

        parsed = _parse_response(raw)

        if parsed is None:
            logger.warning("[AmbiguityResolver] Could not parse LLM response — escalating")
            # Optional: log raw response once for debugging (remove after testing)
            # logger.debug(f"[AmbiguityResolver] raw LLM output was: {raw[:500]}")
            return ResolverResult(
                resolved             = False,
                remaining_candidates = candidates[:_MAX_USER_CANDIDATES],
            )

        best_idx   = parsed.get("best_index")
        confidence = parsed.get("confidence", "low")
        reason     = parsed.get("reason", "")

        # Validate index
        if not isinstance(best_idx, int) or best_idx < 0 or best_idx >= len(candidates):
            logger.warning(
                f"[AmbiguityResolver] Invalid best_index={best_idx!r} for "
                f"{len(candidates)} candidates — escalating"
            )
            return ResolverResult(
                resolved             = False,
                remaining_candidates = candidates[:_MAX_USER_CANDIDATES],
            )

        chosen = candidates[best_idx]

        if confidence in ("high", "medium"):
            logger.info(
                f"[AmbiguityResolver] Auto-resolved '{question[:60]}' → "
                f"'{chosen.get('id')}' (confidence={confidence}, reason={reason})"
            )
            return ResolverResult(
                resolved    = True,
                query_entry = chosen,
                confidence  = confidence,
                reason      = reason,
            )

        # Low confidence — still send LLM's best pick to top of the list
        reordered = [chosen] + [c for c in candidates if c is not chosen]
        logger.info(
            f"[AmbiguityResolver] Low confidence for '{question[:60]}' — "
            f"escalating to user with reordered candidates"
        )
        return ResolverResult(
            resolved             = False,
            remaining_candidates = reordered[:_MAX_USER_CANDIDATES],
        )


class ResolverResult:
    """Result of AmbiguityResolver.resolve()."""

    def __init__(
        self,
        *,
        resolved:             bool,
        query_entry:          Optional[QueryEntry]      = None,
        confidence:           str                       = "",
        reason:               str                       = "",
        remaining_candidates: Optional[List[QueryEntry]] = None,
    ) -> None:
        self.resolved             = resolved
        self.query_entry          = query_entry
        self.confidence           = confidence
        self.reason               = reason
        self.remaining_candidates: List[QueryEntry] = remaining_candidates or []


def _parse_response(raw: str) -> Optional[Dict[str, Any]]:
    """Robust parser that works with llama-3.3-70b-versatile AND openai/gpt-oss-120b."""
    if not raw:
        return None
    text = raw.strip()

    # Strip markdown code blocks (```json and ```) — this was the exact failure
    text = re.sub(r'```(?:json)?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'```\s*$', '', text, flags=re.IGNORECASE).strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract the first valid JSON object (handles extra text around it)
    m = re.search(r'(\{[\s\S]*?\})', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    return None