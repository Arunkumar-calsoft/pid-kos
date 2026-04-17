# agent/cypher_validator.py
"""
Shared Cypher Validator

Single source of truth for structural validation of LLM-generated Cypher
before execution. Extracted from registry_enricher.py and grounded_generator.py
which previously each maintained a private copy.

Used by:
  - agent/grounded_generator.py   (Tier 2.5 — LLM-powered generation)
  - agent/registry_enricher.py    (offline enrichment pipeline)

Checks:
  1. Read-only guard     — no write operations
  2. Label guard         — only verified node labels from schema_context
  3. Rel type guard      — only verified rel types from schema_context
  4. RETURN clause       — query must return results
  5. EXPLAIN             — optional syntax check via Neo4j EXPLAIN
  6. Dry-run execution   — optional sample row collection
  7. Evidence.direction  — warning when accessing always-null field
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Any

from agent.schema_context import NODE_PROPERTIES, REL_TYPES

logger = logging.getLogger(__name__)

_VALID_LABELS    = set(NODE_PROPERTIES.keys())
_WRITE_KEYWORDS  = {"CREATE", "MERGE", "SET", "DELETE", "REMOVE", "DROP", "DETACH"}


class ValidationResult:
    """Result of a CypherValidator.validate() call."""

    def __init__(
        self,
        *,
        valid:  bool,
        reason: str,
        cypher: str,
        sample: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.valid  = valid
        self.reason = reason
        self.cypher = cypher
        self.sample: List[Dict[str, Any]] = sample or []

    def __repr__(self) -> str:
        return f"ValidationResult(valid={self.valid}, reason={self.reason!r})"


class CypherValidator:
    """
    Lightweight structural validator for LLM-generated Cypher.

    Not a full parser — catches the most common failure modes:
      - Write operations
      - Unknown node labels
      - Unknown relationship types
      - Missing RETURN clause
      - Evidence.direction usage (always null — use observed_direction)

    Optional neo4j_runner enables EXPLAIN (syntax check) and dry-run
    execution to collect sample rows.
    """

    def __init__(self, neo4j_runner: Optional[Any] = None) -> None:
        self._runner = neo4j_runner

    def validate(self, cypher: str) -> ValidationResult:
        """
        Validate a Cypher string.

        Returns:
            ValidationResult with valid=True when all checks pass,
            or valid=False with a reason string on first failure.
        """
        upper_tokens = set(cypher.upper().split())

        # 1. Read-only guard
        write_found = upper_tokens & _WRITE_KEYWORDS
        if write_found:
            return ValidationResult(
                valid=False,
                reason=f"Write operation detected: {write_found}",
                cypher=cypher,
            )

        # 2. Label guard
        used_labels    = set(re.findall(r"(?<=:)([A-Z][A-Za-z]+)(?=[\s\)\{])", cypher))
        unknown_labels = used_labels - _VALID_LABELS
        if unknown_labels:
            return ValidationResult(
                valid=False,
                reason=f"Unknown node labels: {unknown_labels}",
                cypher=cypher,
            )

        # 3. Relationship type guard
        used_rels    = set(re.findall(r"\[:([A-Z_]+)\]", cypher))
        unknown_rels = used_rels - REL_TYPES
        if unknown_rels:
            return ValidationResult(
                valid=False,
                reason=f"Unknown relationship types: {unknown_rels}",
                cypher=cypher,
            )

        # 4. RETURN clause
        if "RETURN" not in cypher.upper():
            return ValidationResult(
                valid=False,
                reason="Missing RETURN clause",
                cypher=cypher,
            )

        # 5. Evidence.direction warning (observed_direction is preferred)
        if re.search(r"\be\.direction\b", cypher) and "e.observed_direction" not in cypher:
            logger.warning(
                "[CypherValidator] Evidence.direction exists but Evidence.observed_direction "
                "is the preferred canonical value. Consider using observed_direction instead."
            )

        # 6. Optional: EXPLAIN syntax check
        if self._runner is not None:
            try:
                self._runner.run(f"EXPLAIN {cypher}")
            except Exception as exc:
                return ValidationResult(
                    valid=False,
                    reason=f"Syntax error (EXPLAIN): {exc}",
                    cypher=cypher,
                )

        # 7. Optional: dry-run execution — collect sample rows
        sample: List[Dict[str, Any]] = []
        if self._runner is not None:
            try:
                sample = self._runner.run(cypher)
            except Exception as exc:
                return ValidationResult(
                    valid=False,
                    reason=f"Execution failed: {exc}",
                    cypher=cypher,
                )

        return ValidationResult(
            valid=True,
            reason="ok",
            cypher=cypher,
            sample=sample[:3],
        )