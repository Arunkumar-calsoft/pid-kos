# agent/query_logger.py
"""
Query Logger

Records every query outcome to a JSONL log file.
The log is the input feed for RegistryEnricher (offline pipeline).

Log entry schema:
{
    "ts":           ISO timestamp,
    "question":     str,
    "intent_type":  str,
    "strategy":     "template" | "registry_file" | "llm_grounded" | "schema_generated",
    "query_id":     str,
    "query_title":  str,
    "record_count": int,
    "outcome":      "ok" | "zero_results" | "ambiguous" | "unknown_intent" | "error",
    "error":        str | null,
    "slots":        dict,
}

Outcomes that trigger RegistryEnricher:
    zero_results    → query ran but returned nothing
    unknown_intent  → IntentParser could not classify
    ambiguous       → LogicalPlanBuilder tied on two candidates
    error           → runtime failure
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "query_log.jsonl"


class QueryLogger:

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self._path = log_path or _DEFAULT_LOG_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_success(
        self,
        *,
        question:    str,
        intent:      Dict[str, Any],
        query_id:    str,
        query_title: str,
        strategy:    str,
        records:     int,
    ) -> None:
        outcome = "zero_results" if records == 0 else "ok"
        self._write({
            "question":     question,
            "intent_type":  intent.get("intent_type", "unknown_intent"),
            "strategy":     strategy,
            "query_id":     query_id,
            "query_title":  query_title,
            "record_count": records,
            "outcome":      outcome,
            "error":        None,
            "slots":        intent.get("slots", {}),
        })

    def log_ambiguity(
        self,
        *,
        question:    str,
        intent:      Dict[str, Any],
        candidates:  list,
    ) -> None:
        self._write({
            "question":     question,
            "intent_type":  intent.get("intent_type", "unknown_intent"),
            "strategy":     None,
            "query_id":     None,
            "query_title":  None,
            "record_count": None,
            "outcome":      "ambiguous",
            "error":        f"Tied candidates: {[c['id'] for c in candidates]}",
            "slots":        intent.get("slots", {}),
        })

    def log_unknown_intent(
        self,
        *,
        question: str,
        intent:   Dict[str, Any],
    ) -> None:
        self._write({
            "question":     question,
            "intent_type":  "unknown_intent",
            "strategy":     None,
            "query_id":     None,
            "query_title":  None,
            "record_count": None,
            "outcome":      "unknown_intent",
            "error":        None,
            "slots":        intent.get("slots", {}),
        })

    def log_error(
        self,
        *,
        question: str,
        intent:   Optional[Dict[str, Any]],
        error:    Exception,
    ) -> None:
        self._write({
            "question":     question,
            "intent_type":  intent.get("intent_type") if intent else None,
            "strategy":     None,
            "query_id":     None,
            "query_title":  None,
            "record_count": None,
            "outcome":      "error",
            "error":        f"{type(error).__name__}: {error}",
            "slots":        intent.get("slots", {}) if intent else {},
        })

    # ------------------------------------------------------------------
    # Queries for RegistryEnricher
    # ------------------------------------------------------------------

    def read_failures(self) -> list:
        """Return all log entries that warrant enrichment attention."""
        if not self._path.exists():
            return []
        failures = []
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("outcome") in {
                        "zero_results", "unknown_intent", "ambiguous", "error"
                    }:
                        failures.append(entry)
                except json.JSONDecodeError:
                    continue
        return failures

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(self, payload: Dict[str, Any]) -> None:
        payload["ts"] = datetime.now(timezone.utc).isoformat()
        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
        except OSError as exc:
            logger.warning(f"[QueryLogger] Failed to write log: {exc}")