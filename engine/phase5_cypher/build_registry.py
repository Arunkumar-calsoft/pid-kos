"""
Phase-5 Query Registry Builder (Atomic + Strict + Deterministic + Semantic)

Builds:
    phase5_cypher/_meta/queries.json

Design Guarantees:
- One file = one query
- No inline Cypher stored
- Atomic validation enforced
- Deterministic structure
- Strict schema
- Metadata-rich registry
- No heuristic runtime routing
"""

from __future__ import annotations

import sys
import io
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, TypedDict, List
import json
import re


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR: Path = Path(__file__).parent
META_DIR: Path = BASE_DIR / "_meta"
OUT_FILE: Path = META_DIR / "queries.json"

CYPHER_EXT: str = ".cypher"
BASE_PATH_VALUE: str = "."

# Queries that require runtime parameters beyond $pid_id (e.g. $start_equipment).
# Phase 6 batch mode only supplies $pid_id, so these must be excluded from
# the verified set and invoked only by the agent with explicit parameters.
_REQUIRES_RUNTIME_PARAMS: frozenset[str] = frozenset({
    "reachability_corrected_09_everything_reachable_from_given_equipment",
})


# ---------------------------------------------------------------------------
# Typed Schema Definitions
# ---------------------------------------------------------------------------

class QueryEntry(TypedDict):
    id: str
    title: str
    intent: str
    category: str
    cypher_file: str
    verified: bool

    # New deterministic metadata
    target_entity: str
    operation: str
    scope: str
    output_type: str

    required_keywords: List[str]
    boost_keywords: List[str]
    exclude_keywords: List[str]


class RegistryMeta(TypedDict):
    name: str
    version: str
    generated_at: str
    query_count: int
    base_path: str


class RegistryDocument(TypedDict):
    registry: RegistryMeta
    queries: Dict[str, QueryEntry]


# ---------------------------------------------------------------------------
# Intent Mapping
# ---------------------------------------------------------------------------

INTENT_MAP: Dict[str, str] = {
    "directionality": "flow_direction",
    "external": "external_interfaces",
    "inventory": "engineering_inventory",
    "topology": "connectivity_topology",
    "lines": "line_attributes",
    "instruments": "instrument_attachment",
    "valves": "valve_placement",
    "redundancy": "redundancy_patterns",
    "reachability": "isolation_reachability",
    "quality": "drawing_consistency",
    # ── New categories from Question Catalogue v5 ──
    "annotations": "annotation_requests",
    "cross_domain": "cross_domain",
    "engineering_correctness": "engineering_correctness",
    "equipment_semantics": "cross_domain",
    "flow_coverage": "flow_coverage",
    "flow_nodes": "flow_direction",
    "pipe_edges": "connectivity_topology",
}


def infer_intent(category: str) -> str:
    return INTENT_MAP.get(category, "unknown_intent")


# ---------------------------------------------------------------------------
# Deterministic Semantic Inference
# ---------------------------------------------------------------------------

def infer_target_entity(category: str, stem_tokens: List[str]) -> str:
    if "equipment" in stem_tokens:
        return "equipment"
    if "symbol" in stem_tokens:
        return "symbol"
    if "pipe" in stem_tokens:
        return "pipe_segment"
    if "instrument" in stem_tokens:
        return "instrument"
    return category


def infer_operation(stem_tokens: List[str], cypher_path: Path | None = None) -> str:
    # 1. Check the // Operation: comment in the .cypher file (most reliable)
    if cypher_path is not None:
        try:
            text = cypher_path.read_text(encoding="utf-8")
            m = re.search(r'//\s*Operation:\s*(\w+)', text, re.IGNORECASE)
            if m:
                op = m.group(1).lower()
                if op in ("count", "list", "path", "query", "reachability"):
                    return op
        except Exception:
            pass
    # 2. Fall back to stem token heuristics
    if "count" in stem_tokens or "how" in stem_tokens:
        return "count"
    if "list" in stem_tokens:
        return "list"
    if "path" in stem_tokens:
        return "path"
    if "isolated" in stem_tokens:
        return "reachability"
    return "query"


def infer_scope(category: str) -> str:
    if category in {"reachability", "topology"}:
        return "structural"
    if category == "quality":
        return "validation"
    return "engineering"


def infer_output_type(operation: str) -> str:
    if operation == "count":
        return "single_value"
    if operation == "list":
        return "collection"
    if operation == "path":
        return "path"
    return "records"


# Words that carry no intent value — stripped from boost keyword lists.
_NOISE_WORDS = {
    "q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "q9", "q10",
    "q11", "q12", "q13", "q14", "q15", "q16", "q17", "q18", "q19", "q20",
    "a", "an", "the", "is", "are", "on", "in", "of", "to", "for", "with",
    "this", "that", "be", "and", "or", "how", "many", "there", "what",
    "does", "do", "show", "list", "all", "any", "each", "per", "by",
    "their", "its", "they", "drawing", "exist", "exists",
}


def _extract_question_keywords(cypher_path: Path) -> List[str]:
    """Extract keywords from the '// Engineer question:' comment in a .cypher file."""
    try:
        text = cypher_path.read_text(encoding="utf-8")
        m = re.search(r'//\s*Engineer question:\s*"(.+?)"', text)
        if not m:
            return []
        question = m.group(1).lower()
        tokens = re.findall(r'[a-z]{2,}', question)
        return [t for t in tokens if t not in _NOISE_WORDS]
    except Exception:
        return []


def _extract_required_keywords(cypher_path: Path) -> List[str]:
    """Extract explicit required keywords from '// Required keywords: a, b, c' comment."""
    try:
        text = cypher_path.read_text(encoding="utf-8")
        m = re.search(r'//\s*Required keywords:\s*(.+)', text)
        if not m:
            return []
        raw = m.group(1).strip()
        return [t.strip().lower() for t in re.split(r'[,\s]+', raw) if t.strip()]
    except Exception:
        return []


def build_keyword_metadata(
    stem_tokens: List[str],
    cypher_path: Path | None = None,
) -> tuple:
    required: List[str] = []
    boost: List[str] = []
    exclude: List[str] = []

    # 1. Special-case rules (original behaviour)
    if "isolated" in stem_tokens:
        required.append("isolated")
    if "equipment" in stem_tokens:
        boost.append("equipment")
        exclude.append("symbol")
    if "symbol" in stem_tokens:
        boost.append("symbol")
        boost.append("node")
        exclude.append("equipment")

    # 2. Stem tokens → boost keywords (minus noise words and digits)
    for t in stem_tokens:
        if t in _NOISE_WORDS or t.isdigit() or len(t) < 3:
            continue
        if t not in boost:
            boost.append(t)

    # 3. Engineer-question keywords from .cypher file comments
    if cypher_path is not None:
        for kw in _extract_question_keywords(cypher_path):
            if kw not in boost and kw not in _NOISE_WORDS:
                boost.append(kw)

    # 4. Explicit required keywords from '// Required keywords:' comment
    #    These override and supplement the auto-inferred list, giving .cypher authors
    #    precise control over when a query fires. Common use: specialized queries
    #    that share a subject word with a base query (e.g. instruments_connected_valves
    #    requires "valve" so it doesn't win for "show all instruments").
    if cypher_path is not None:
        for kw in _extract_required_keywords(cypher_path):
            if kw not in required:
                required.append(kw)

    return required, boost, exclude


# ---------------------------------------------------------------------------
# Atomic Cypher Validation
# ---------------------------------------------------------------------------

def is_atomic_cypher(path: Path) -> bool:

    text = path.read_text(encoding="utf-8")

    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    text = re.sub(r"//.*", "", text)

    stripped = text.strip()
    if not stripped:
        return False

    statements = [s.strip() for s in stripped.split(";") if s.strip()]

    if len(statements) != 1:
        return False

    if "RETURN" not in statements[0].upper():
        return False

    return True


# ---------------------------------------------------------------------------
# Registry Builder
# ---------------------------------------------------------------------------

def build_registry() -> None:
    all_queries: Dict[str, QueryEntry] = {}

    category_dirs = sorted(
        p for p in BASE_DIR.iterdir()
        if p.is_dir() and p.name != "_meta"
    )

    for category_dir in category_dirs:
        category = category_dir.name
        cypher_files = sorted(category_dir.glob(f"*{CYPHER_EXT}"))

        for cypher_file in cypher_files:

            if not is_atomic_cypher(cypher_file):
                print(f"[SKIP] Ignoring non-atomic file → {cypher_file.name}")
                continue

            query_id = f"{category}_{cypher_file.stem}"

            if query_id in all_queries:
                raise ValueError(f"Duplicate query id detected: {query_id}")

            rel_path = str(
                cypher_file.relative_to(BASE_DIR)
            ).replace("\\", "/")

            stem_tokens = cypher_file.stem.lower().split("_")

            operation = infer_operation(stem_tokens, cypher_file)

            required, boost, exclude = build_keyword_metadata(stem_tokens, cypher_file)

            entry: QueryEntry = {
                "id": query_id,
                "title": cypher_file.stem.replace("_", " "),
                "intent": infer_intent(category),
                "category": category,
                "cypher_file": rel_path,
                "verified": query_id not in _REQUIRES_RUNTIME_PARAMS,

                # New metadata
                "target_entity": infer_target_entity(category, stem_tokens),
                "operation": operation,
                "scope": infer_scope(category),
                "output_type": infer_output_type(operation),
                "required_keywords": required,
                "boost_keywords": boost,
                "exclude_keywords": exclude,
            }

            all_queries[query_id] = entry

    META_DIR.mkdir(exist_ok=True)

    # query_count must match the number of VERIFIED queries only,
    # because query_registry.py validates len(verified) == meta["query_count"].
    # Unverified entries (those in _REQUIRES_RUNTIME_PARAMS) are intentionally
    # excluded from the verified set and must not be counted here.
    verified_count = sum(1 for e in all_queries.values() if e["verified"])

    registry_meta: RegistryMeta = {
        "name": "phase5-cypher-registry",
        "version": "3.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query_count": verified_count,
        "base_path": BASE_PATH_VALUE,
    }

    registry_doc: RegistryDocument = {
        "registry": registry_meta,
        "queries": all_queries,
    }

    OUT_FILE.write_text(
        json.dumps(registry_doc, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"[OK] Registry written -> {OUT_FILE.resolve()}")
    print(f"[OK] Queries indexed  -> {len(all_queries)}")


if __name__ == "__main__":
    build_registry()