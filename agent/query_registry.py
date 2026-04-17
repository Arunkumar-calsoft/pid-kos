# agent/query_registry.py
"""
Query Registry — Shared Authority

Responsibilities:
- Load phase5_cypher/_meta/queries.json
- Enforce exact registry schema
- Validate metadata + base_path
- Enforce verified-only execution
- Resolve cypher files safely (Tier 2 — Phase 5 pre-validated)

Used by:
    LogicalPlanBuilder  → reads .queries list
    HybridOptimizer     → calls .resolve_cypher() at Tier 2 (before LLM)
    RegistryEnricher    → reads + writes queries.json for new entries
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict, Any, TypedDict

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BASE_DIR      = Path(__file__).resolve().parents[1] / "engine" / "phase5_cypher"
_REGISTRY_PATH = _BASE_DIR / "_meta" / "queries.json"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class QueryEntry(TypedDict):
    id:                str
    title:             str
    intent:            str
    category:          str
    cypher_file:       str
    verified:          bool
    target_entity:     str
    operation:         str
    scope:             str
    output_type:       str
    required_keywords: List[str]
    boost_keywords:    List[str]
    exclude_keywords:  List[str]


_REQUIRED_QUERY_FIELDS = {
    "id", "title", "intent", "category", "cypher_file", "verified",
    "target_entity", "operation", "scope", "output_type",
    "required_keywords", "boost_keywords", "exclude_keywords",
}

_REQUIRED_REGISTRY_META_FIELDS = {
    "name", "version", "generated_at", "query_count", "base_path",
}

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class QueryRegistry:
    def __init__(self, *, queries: List[QueryEntry], base_path: Path) -> None:
        self._queries   = queries
        self._base_path = base_path

    @property
    def queries(self) -> List[QueryEntry]:
        return self._queries

    def resolve_cypher(self, entry: QueryEntry) -> str:
        cypher_path = (self._base_path / entry["cypher_file"]).resolve()
        if self._base_path not in cypher_path.parents:
            raise RuntimeError("Unsafe cypher path escape detected.")
        if not cypher_path.exists():
            raise FileNotFoundError(f"Cypher file not found: {cypher_path}")
        return cypher_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_registry() -> QueryRegistry:
    if not _REGISTRY_PATH.exists():
        raise FileNotFoundError(
            f"Registry not found at {_REGISTRY_PATH}. Run build_registry first."
        )

    raw = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))

    if not isinstance(raw, dict):
        raise TypeError("Registry root must be a dict.")
    if "registry" not in raw or "queries" not in raw:
        raise ValueError("Registry must contain 'registry' and 'queries'.")

    meta         = raw["registry"]
    queries_blob = raw["queries"]

    _validate_registry_meta(meta)

    base_path = (_REGISTRY_PATH.parent.parent / meta["base_path"]).resolve()
    if not base_path.exists():
        raise RuntimeError(f"Base path does not exist: {base_path}")

    if not isinstance(queries_blob, dict):
        raise TypeError("'queries' must be a dict keyed by query id.")

    validated: List[QueryEntry] = []
    for qid, entry in queries_blob.items():
        _validate_query_entry(entry, qid)
        if entry["verified"] is True:
            validated.append(entry)  # type: ignore

    if not validated:
        raise RuntimeError("No VERIFIED queries available in registry.")
    if len(validated) != meta["query_count"]:
        raise RuntimeError("Registry query_count mismatch.")

    return QueryRegistry(queries=validated, base_path=base_path)


def _validate_registry_meta(meta: Dict[str, Any]) -> None:
    missing = _REQUIRED_REGISTRY_META_FIELDS - meta.keys()
    if missing:
        raise ValueError(f"Registry metadata missing fields: {missing}")
    if not isinstance(meta["version"], str):
        raise TypeError("Registry version must be string.")
    if not isinstance(meta["base_path"], str):
        raise TypeError("Registry base_path must be string.")


def _validate_query_entry(entry: Dict[str, Any], qid: str) -> None:
    if not isinstance(entry, dict):
        raise TypeError(f"Query '{qid}' must be dict.")
    missing = _REQUIRED_QUERY_FIELDS - entry.keys()
    if missing:
        raise ValueError(f"Query '{qid}' missing fields: {missing}")
    if not isinstance(entry["intent"], str):
        raise TypeError(f"Invalid intent in query '{qid}'")
    if not isinstance(entry["cypher_file"], str):
        raise TypeError(f"Invalid cypher_file in query '{qid}'")
    if not isinstance(entry["required_keywords"], list):
        raise TypeError(f"required_keywords must be list in '{qid}'")
    if not isinstance(entry["exclude_keywords"], list):
        raise TypeError(f"exclude_keywords must be list in '{qid}'")