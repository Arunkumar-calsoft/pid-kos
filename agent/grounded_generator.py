# agent/grounded_generator.py
"""
Grounded Cypher Generator

LLM-powered Cypher generation using the verified schema context.
Replaces the hardcoded _GENERATORS dict in hybrid_optimizer.py.

SchemaGenerator.generate() calls GroundedGenerator.generate() when an
LLM client is available. Falls back to the hardcoded generators when not.

The generator:
  1. Injects the full grounded schema context into the system prompt
  2. Injects the capability map for the specific intent bucket
  3. Asks the LLM to generate Cypher constrained strictly to verified schema
  4. Validates the response (read-only, labels, rel types)
  5. Returns validated Cypher or raises NotImplementedError for fallback

Design:
  - Stateless
  - Never mutates intent or query_entry
  - On any LLM failure → raises NotImplementedError so HybridOptimizer
    falls through to SchemaGenerator (Tier 4) gracefully
"""
from __future__ import annotations

import logging
import re
from typing import Dict, Any, Optional, List

from agent.llm_client import LLMClient
from agent.types_shared import GeneratorResult
from agent.schema_context import (
    SCHEMA_PROMPT,
    SCHEMA_PROMPT_COMPACT,
    SCHEMA_PROMPT_MINIMAL,
    CAPABILITY_MAP,
    REL_TYPES,
    NODE_PROPERTIES,
    QUERY_RULES,
)

logger = logging.getLogger(__name__)

# Labels that are valid to use in Cypher
_VALID_LABELS = set(NODE_PROPERTIES.keys())

# Write keywords that must never appear
_WRITE_KEYWORDS = {"CREATE", "MERGE", "SET", "DELETE", "REMOVE", "DROP", "DETACH"}

# ---------------------------------------------------------------------------
# Schema tier selection
#
# Three schema tiers matched to model context budgets:
#   full    — SCHEMA_PROMPT        (~7800 tokens): large models (budget >= 10k)
#   compact — SCHEMA_PROMPT_COMPACT (~1200 tokens): mid models  (budget >= 2500)
#   minimal — SCHEMA_PROMPT_MINIMAL  (~400 tokens): small/rate-limited models
#
# The per-intent capability notes are ALWAYS injected on top of the schema,
# so even the minimal tier gets the intent-specific warnings and example Cypher.
# ---------------------------------------------------------------------------

def _select_schema(llm_client: LLMClient) -> str:
    """Return the right schema string for the current LLM model's budget."""
    budget = getattr(llm_client, "context_budget", 8000)
    if budget >= 10000:
        return SCHEMA_PROMPT
    if budget >= 2500:
        return SCHEMA_PROMPT_COMPACT
    return SCHEMA_PROMPT_MINIMAL


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """
You are a Neo4j Cypher query generator for a P&ID (Piping and Instrumentation Diagram) graph database.

{schema}

=== CAPABILITY CONTEXT FOR THIS QUERY ===
Intent bucket: {intent_type}
Description: {capability_description}
{capability_notes}

=== HARD RULES — ALWAYS OBEY ===
1. Scoping to a PID: Two equivalent methods are valid:
   Option A — WHERE filter (simpler, preferred):
     MATCH (n:Node) WHERE n.pid_id = "{pid_id}"
   Option B — traverse from PID (use when you need PID properties):
     MATCH (p:PID {{pid_id:"{pid_id}"}})-[:CONTAINS]->(n:Node)
   Both are correct. Do NOT use both in the same query (redundant).
   Always include pid_id filtering when pid_id is provided.

2. "Connected" between two symbol types = reachable via PIPE path of ANY length.
   Use EXISTS {{ MATCH (a)-[:PIPE*1..20]-(b) }} for multi-hop connectivity.
   A single (a)-[:PIPE]-(b) hop will almost always return zero for symbol-to-symbol.

3. Always include AND <alias>.pid_id = "{pid_id}" in every WHERE clause when
   pid_id is provided. Apply it to EVERY node alias in the query.

4. COVERS direction: LogicalPipeSegment → PipeSegment (not the reverse).
   To find which LPS covers a PipeSegment:
     MATCH (lps:LogicalPipeSegment)-[:COVERS]->(ps:PipeSegment)
   To find the LPS for a valve node:
     MATCH (v:Node {{label:'valve'}})<-[:CONTAINS]-(ps:PipeSegment)<-[:COVERS]-(lps:LogicalPipeSegment)
   Never write (ps)-[:COVERS]->(lps).

5. For "cannot reach" / "not reachable" / "no path to" queries use NOT EXISTS:
     WHERE NOT EXISTS {{
       MATCH (n)-[:PIPE*1..30]-(target:Node {{label:'inlet/outlet'}})
     }}
   This is the ONLY correct pattern for negative reachability — never try to
   infer absence from zero-row counts across multiple queries.

=== YOUR TASK ===
Generate a single, correct, read-only Cypher query that answers the user's question.

Output format:
  - Return ONLY the raw Cypher query
  - No explanation, no markdown fences, no preamble, no comments
  - The query must be executable as-is
  - Always include LIMIT on list queries (default 50)
  - Always alias aggregations: count(n) AS total
  - Include the symbol label in RETURN columns so the answer can reference it by name
""".strip()


def _build_system_prompt(intent_type: str, pid_id: str = "UNKNOWN",
                         schema: str | None = None) -> str:
    if schema is None:
        schema = SCHEMA_PROMPT_COMPACT
    cap = CAPABILITY_MAP.get(intent_type, {})
    description = cap.get("description", "General graph query")

    notes_parts: List[str] = []
    if "filter" in cap:
        notes_parts.append(f"Primary filter: {cap['filter']}")
    if "warnings" in cap:
        for w in cap["warnings"]:
            notes_parts.append(f"⚠️  WARNING: {w}")
    elif "warning" in cap:
        notes_parts.append(f"⚠️  WARNING: {cap['warning']}")
    if "via_annotation" in cap:
        notes_parts.append(f"Query via: {cap['via_annotation']}")
    if "side_detection" in cap:
        notes_parts.append(f"Side detection: {cap['side_detection']}")
    if "annotation_types_for_quality" in cap:
        types = ", ".join(f"'{t}'" for t in cap["annotation_types_for_quality"])
        notes_parts.append(f"Relevant annotation types: {types}")
    if "note" in cap:
        notes_parts.append(f"Note: {cap['note']}")
    if "traversal" in cap:
        notes_parts.append(f"Traversal pattern: {cap['traversal']}")
    if "primary_rel" in cap:
        notes_parts.append(f"Primary relationship: {cap['primary_rel']}")
    if "example_cypher" in cap:
        notes_parts.append(f"Example Cypher pattern:\n{cap['example_cypher']}")

    return _SYSTEM_PROMPT_TEMPLATE.format(
        schema                 = schema,
        intent_type            = intent_type,
        capability_description = description,
        capability_notes       = "\n".join(notes_parts) if notes_parts else "",
        pid_id                 = pid_id if pid_id != "UNKNOWN" else "<pid_id>",
    )


# ---------------------------------------------------------------------------
# Cypher validator
# ---------------------------------------------------------------------------

class _CypherValidator:
    """
    Lightweight structural validation before executing LLM-generated Cypher.
    Not a full parser — catches the most common failure modes.
    """

    def validate(self, cypher: str, pid_id: Optional[str] = None) -> Optional[str]:
        """
        Returns None if valid, or an error message string if invalid.
        pid_id: when provided and not 'UNKNOWN', checks that the query
                includes pid_id scoping to prevent cross-drawing data leakage.
        """
        upper_tokens = set(cypher.upper().split())

        # Read-only check
        if upper_tokens & _WRITE_KEYWORDS:
            found = upper_tokens & _WRITE_KEYWORDS
            return f"Write operation detected: {found}"

        # Label check
        used_labels = set(re.findall(r"(?<=:)([A-Z][A-Za-z]+)(?=[\s\)\{])", cypher))
        unknown = used_labels - _VALID_LABELS
        if unknown:
            return f"Unknown node labels: {unknown}"

        # Relationship type check
        used_rels = set(re.findall(r"\[:([A-Z_]+)\]", cypher))
        unknown_rels = used_rels - REL_TYPES
        if unknown_rels:
            return f"Unknown relationship types: {unknown_rels}"

        # Must have RETURN
        if "RETURN" not in cypher.upper():
            return "Missing RETURN clause"

        # Multi-statement detection — the LLM sometimes concatenates
        # multiple queries.  Neo4j cannot execute them as one string.
        # Count top-level RETURN keywords (not inside EXISTS/CALL blocks).
        _stripped = re.sub(r'EXISTS\s*\{[^}]*\}', '', cypher, flags=re.DOTALL | re.IGNORECASE)
        _return_count = len(re.findall(r'\bRETURN\b', _stripped, re.IGNORECASE))
        if _return_count > 1:
            return (
                f"Multi-statement query detected ({_return_count} RETURN clauses). "
                "Generate a single Cypher query, not multiple concatenated queries."
            )

        # pid_id scoping check — every query must be scoped to a single drawing
        # to prevent data leakage across PIDs. Two valid patterns:
        #   Option A: n.pid_id (WHERE n.pid_id = "...")
        #   Option B: {pid_id: (MATCH (p:PID {pid_id: ...}))
        if pid_id and pid_id != "UNKNOWN":
            if "pid_id" not in cypher:
                return (
                    "Missing pid_id scoping — query must filter by pid_id "
                    "(e.g. WHERE n.pid_id = $pid_id) to avoid returning data "
                    "from all drawings."
                )

        # Warn about Evidence.direction usage (always null)
        if "e.direction" in cypher and "e.observed_direction" not in cypher:
            logger.warning(
                "[GroundedGenerator] Evidence.direction is always null — "
                "query may return no direction values"
            )

        return None


_validator = _CypherValidator()


# ---------------------------------------------------------------------------
# Grounded Generator
# ---------------------------------------------------------------------------

class GroundedGenerator:
    """
    LLM-powered Cypher generator grounded in the verified schema context.

    Usage:
        generator = GroundedGenerator(llm_client)
        cypher = generator.generate(query_entry, intent)
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    def generate(
        self,
        query_entry: Dict[str, Any],
        intent: Dict[str, Any],
    ) -> GeneratorResult:
        """
        Generate grounded Cypher for the given intent.

        Returns GeneratorResult(cypher, reasoning) so HybridOptimizer can
        populate OptimizerResult.reasoning like the SchemaGenerator does.

        Raises:
            NotImplementedError: if LLM fails, returns empty, or validation fails.
                                  HybridOptimizer will fall through to SchemaGenerator.
        """
        intent_type: str  = intent.get("intent_type", "unknown_intent")
        slots:       Dict = intent.get("slots", {})
        keywords:    List = intent.get("keywords", [])
        question:    str  = intent.get("raw", "")
        pid_id:      str  = intent.get("pid_id", "UNKNOWN")

        if intent_type not in CAPABILITY_MAP and intent_type != "unknown_intent":
            raise NotImplementedError(
                f"[GroundedGenerator] No capability map entry for '{intent_type}'"
            )

        schema  = _select_schema(self._llm)
        system  = _build_system_prompt(intent_type, pid_id, schema=schema)
        message = self._build_user_message(question, intent_type, slots, keywords, pid_id)

        budget  = getattr(self._llm, "context_budget", 8000)
        model   = getattr(self._llm, "current_model", "unknown")
        logger.debug(
            f"[GroundedGenerator] intent='{intent_type}' model={model} "
            f"budget={budget} schema_chars={len(schema)}"
        )

        try:
            raw = self._llm.complete(
                system     = system,
                message    = message,
                max_tokens = 400,
            )
        except Exception as exc:
            logger.warning(f"[GroundedGenerator] LLM call failed: {exc}")
            raise NotImplementedError(f"LLM call failed: {exc}") from exc

        cypher = self._clean_response(raw)

        if not cypher:
            raise NotImplementedError("[GroundedGenerator] LLM returned empty response")

        error = _validator.validate(cypher, pid_id=pid_id)
        if error:
            logger.warning(f"[GroundedGenerator] Validation failed: {error}\n{cypher}")
            raise NotImplementedError(f"Cypher validation failed: {error}")

        logger.debug(f"[GroundedGenerator] Generated for '{intent_type}':\n{cypher}")
        schema_tier = "full" if schema is SCHEMA_PROMPT else ("compact" if schema is SCHEMA_PROMPT_COMPACT else "minimal")
        return GeneratorResult(
            cypher    = cypher,
            reasoning = (
                f"LLM generated Cypher for intent='{intent_type}' "
                f"grounded in {schema_tier} schema context "
                f"(model={model}, pid_id={pid_id})."
            ),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_user_message(
        question:    str,
        intent_type: str,
        slots:       Dict[str, Any],
        keywords:    List[str],
        pid_id:      str = "UNKNOWN",
    ) -> str:
        parts = [f"Question: {question}"]
        parts.append(f"Intent: {intent_type}")

        if pid_id and pid_id != "UNKNOWN":
            parts.append(
                f"Drawing scope: pid_id = \"{pid_id}\" — "
                f"ALL node/relationship WHERE clauses MUST include "
                f'AND <alias>.pid_id = "{pid_id}"'
            )

        if slots.get("tag"):
            parts.append(
                f"Entity referenced: '{slots['tag']}' "
                f"(this is an internal Node.id — filter with WHERE n.id = '{slots['tag']}')"
            )

        if slots.get("numbers"):
            parts.append(f"Numbers mentioned: {slots['numbers']}")

        op_hint = _detect_operation(set(keywords))
        if op_hint:
            parts.append(f"Operation: {op_hint} query")

        return "\n".join(parts)

    @staticmethod
    def _clean_response(raw: str) -> str:
        """Strip markdown fences and whitespace from LLM response."""
        text = raw.strip()
        # Remove ```cypher ... ``` or ``` ... ```
        text = re.sub(r"^```(?:cypher)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        return text.strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_operation(keywords: set) -> Optional[str]:
    if keywords & {"how", "many", "count", "total", "quantity"}:
        return "count"
    if keywords & {"path", "between", "route"}:
        return "path"
    if keywords & {"list", "show", "all", "which", "what"}:
        return "list"
    return None