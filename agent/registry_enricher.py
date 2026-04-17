# agent/registry_enricher.py
"""
Registry Enricher — Offline Pipeline

Standalone script. Run manually or via cron.
Never touches the production query path.

Pipeline:
    1. Read failure log from QueryLogger
    2. For each failure: build schema-grounded LLM prompt
    3. LLM generates candidate Cypher query
    4. Validate candidate (syntax, labels, rel types, read-only, dry-run)
    5. Write approved candidates to enrichment_queue.json for review_cli.py

Usage:
    python -m agent.registry_enricher
    python -m agent.registry_enricher --log-path /custom/path/query_log.jsonl
    python -m agent.registry_enricher --dry-run     # validate only, don't write
    python -m agent.registry_enricher --limit 20    # process at most N failures

LLM:
    Reads from config.json → llm section.
    GROQ_API_KEY must be set as an environment variable.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from agent.llm_client import LLMClient, build_llm_client_from_config
from agent.query_logger import QueryLogger
from agent.cypher_validator import CypherValidator, ValidationResult

# ---------------------------------------------------------------------------
# All schema constants come from schema_context — the single source of truth.
# hybrid_optimizer imports FROM schema_context, not the other way around.
# ---------------------------------------------------------------------------
from agent.schema_context import (
    SCHEMA_PROMPT       as _SCHEMA_PROMPT,
    NODE_PROPERTIES     as SCHEMA_NODE_PROPS,   # Dict[label, List[prop]]
    RELATIONSHIPS       as SCHEMA_RELATIONSHIPS, # List[Tuple[from, rel, to, props]]
    REL_TYPES           as SCHEMA_REL_TYPES,     # Set[str]
    REL_PROPERTIES      as SCHEMA_REL_PROPS,     # Dict[rel, List[prop]]
)

# SCHEMA_NODES derived from NODE_PROPERTIES keys — same as hybrid_optimizer does
from agent.schema_context import NODE_PROPERTIES as _NODE_PROPS
SCHEMA_NODES: List[str] = list(_NODE_PROPS.keys())

logger = logging.getLogger(__name__)

_QUEUE_PATH  = Path(__file__).resolve().parents[1] / "logs" / "enrichment_queue.json"
_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"


# ---------------------------------------------------------------------------
# Schema context string — injected into every enricher LLM prompt
# ---------------------------------------------------------------------------

def _build_schema_context() -> str:
    return _SCHEMA_PROMPT


_SYSTEM_PROMPT = """
You are a Neo4j Cypher query generator for a PID (Piping and Instrumentation
Diagram) graph database.

Your task: given a question that failed in production, generate a correct,
read-only Cypher query that answers it.

{schema_context}

Output format:
  - Return ONLY the raw Cypher query
  - No explanation, no markdown fences, no preamble
  - The query must be executable as-is against the schema described above
""".strip()


def _build_user_prompt(failure: Dict[str, Any]) -> str:
    return (
        f"Failed production query:\n"
        f"  Question    : {failure['question']}\n"
        f"  Intent type : {failure.get('intent_type', 'unknown')}\n"
        f"  Slots       : {json.dumps(failure.get('slots', {}))}\n"
        f"  Failure     : {failure['outcome']}\n\n"
        f"Generate a Cypher query that answers this question."
    )


# ---------------------------------------------------------------------------
# Cypher validator
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Registry Enricher
# ---------------------------------------------------------------------------

class RegistryEnricher:
    def __init__(
        self,
        llm_client:   LLMClient,
        validator:    CypherValidator,
        query_logger: QueryLogger,
        queue_path:   Path = _QUEUE_PATH,
    ) -> None:
        self._llm        = llm_client
        self._validator  = validator
        self._log        = query_logger
        self._queue_path = queue_path
        self._schema_ctx = _build_schema_context()

    def run(
        self,
        *,
        limit:   Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, int]:
        failures = self._log.read_failures()
        if limit:
            failures = failures[:limit]

        stats      = {"processed": 0, "passed": 0, "skipped": 0, "errors": 0}
        candidates = []

        for failure in failures:
            stats["processed"] += 1
            try:
                candidate = self._process_failure(failure)
                if candidate is None:
                    stats["skipped"] += 1
                    continue
                stats["passed"] += 1
                candidates.append(candidate)
                logger.info(f"[Enricher] ✓ {failure['question'][:60]}")
            except Exception as exc:
                stats["errors"] += 1
                logger.warning(f"[Enricher] ✗ {failure['question'][:60]}: {exc}")

        if not dry_run and candidates:
            self._write_queue(candidates)
            logger.info(
                f"[Enricher] Wrote {len(candidates)} candidates → {self._queue_path}"
            )

        return stats

    def _process_failure(self, failure: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        system     = _SYSTEM_PROMPT.format(schema_context=self._schema_ctx)
        message    = _build_user_prompt(failure)
        raw_cypher = self._llm.complete(
            system=system, message=message, max_tokens=400
        )
        cypher = re.sub(r"```(?:cypher)?|```", "", raw_cypher).strip()

        if not cypher:
            return None

        result = self._validator.validate(cypher)
        if not result.valid:
            logger.debug(
                f"[Enricher] Validation failed ({result.reason}) "
                f"for: {failure['question'][:60]}"
            )
            return None

        return {
            "ts":               datetime.now(timezone.utc).isoformat(),
            "question":         failure["question"],
            "intent_type":      failure.get("intent_type"),
            "slots":            failure.get("slots", {}),
            "failure_outcome":  failure["outcome"],
            "generated_cypher": cypher,
            "validation":       result.reason,
            "sample_records":   result.sample,
            "status":           "pending_review",
        }

    def _write_queue(self, candidates: List[Dict[str, Any]]) -> None:
        self._queue_path.parent.mkdir(parents=True, exist_ok=True)
        existing: List[Dict] = []
        if self._queue_path.exists():
            try:
                existing = json.loads(
                    self._queue_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError):
                existing = []
        all_entries = existing + candidates
        self._queue_path.write_text(
            json.dumps(all_entries, indent=2), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Registry Enricher — offline LLM pipeline"
    )
    parser.add_argument("--log-path",   type=Path, default=None)
    parser.add_argument("--queue-path", type=Path, default=_QUEUE_PATH)
    parser.add_argument("--limit",      type=int,  default=None)
    parser.add_argument("--dry-run",    action="store_true")
    args = parser.parse_args()

    cfg     = json.loads(_CONFIG_PATH.read_text()) if _CONFIG_PATH.exists() else {}
    llm_cfg = cfg.get("llm", {})
    llm     = build_llm_client_from_config(llm_cfg)

    if llm is None:
        raise SystemExit(
            "[RegistryEnricher] LLM client could not be initialised.\n"
            "Check that GROQ_API_KEY is set and config.json is present."
        )

    enricher = RegistryEnricher(
        llm_client   = llm,
        validator    = CypherValidator(),
        query_logger = QueryLogger(log_path=args.log_path),
        queue_path   = args.queue_path,
    )

    stats = enricher.run(limit=args.limit, dry_run=args.dry_run)
    print(
        f"\nDone. processed={stats['processed']} passed={stats['passed']} "
        f"skipped={stats['skipped']} errors={stats['errors']}"
    )


if __name__ == "__main__":
    main()