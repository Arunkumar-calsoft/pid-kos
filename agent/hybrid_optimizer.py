# agent/hybrid_optimizer.py
"""
Hybrid Optimizer — Layer 3

Four-tier resolution (fixed queries first, LLM for custom):
    1. TemplateMatcher    — hardcoded Cypher keyed by query id (zero latency)
    2. Registry file      — pre-validated .cypher from Phase 5 (fixed queries)
                            Used when question maps cleanly to a registry entry
                            without needing entity-specific customisation.
    3. GroundedGenerator  — LLM generates Cypher grounded in verified schema
                            (handles custom phrasing, entity filters, complex
                            conditions that fixed queries cannot express)
    4. SchemaGenerator    — hardcoded generators as last-resort fallback when
                            LLM is unavailable and no registry file matched

SCHEMA SOURCE OF TRUTH: agent/schema_context.py
All node labels, relationship types, property keys, and enum values
are verified against the live Neo4j database. Generators import
from schema_context — do NOT duplicate schema knowledge here.

KEY SCHEMA FACTS THAT DIFFER FROM NAIVE ASSUMPTIONS:
  - Node.label  = symbol CLASS  ('valve','tank','instrumentation','inlet/outlet',
                                  'connector','arrow','crossing','general','background')
  - Node.structural_type = 'SYMBOL' | 'CONNECTOR'
  - background nodes (label='background') are filtered at Phase 0 and never loaded — always
    exclude them with: WHERE n.label <> 'background'
  - External interfaces = Node WHERE label='inlet/outlet'  (structural_type='SYMBOL')
  - Equipment node does NOT exist in graph — use Node.label for equipment queries
  - No OCR tag names — identity is Node.id or Node.label (class)
  - Flow direction lives on LogicalPipeSegment.flow_direction
    BUT only when LogicalPipeSegment.flow_state IN ['SEEDED','PROPAGATED']
  - Evidence.direction exists but prefer Evidence.observed_direction (more reliable)
  - Quality issues are PRE-COMPUTED as Annotation.type values — do not
    recompute structural checks from scratch when possible
  - Annotation.type is the discriminator, not Annotation.attach_status
  - PIPE is the Node-level adjacency — traverse both directions: (n)-[:PIPE]-(m)
  - Degree: use size([(n)-[:PIPE]-(m:Node) | m]) — list comprehension form
    NOT size((n)-[:PIPE]-()) after a WITH clause
"""
from __future__ import annotations

import logging
import re
from typing import Dict, Any, Optional, List

from agent.query_registry import QueryEntry, QueryRegistry
from agent.types_shared import GeneratorResult, OptimizerResult
from agent.schema_context import (
    REL_TYPES,
    NODE_PROPERTIES,
    CAPABILITY_MAP,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema node/rel lists — derived from schema_context so there is one source
# ---------------------------------------------------------------------------

SCHEMA_NODES = list(NODE_PROPERTIES.keys())
SCHEMA_REL_TYPES = REL_TYPES

# Characters allowed in slot values used inside Cypher templates.
# Prevents Cypher injection via user-controlled input (e.g. node IDs, labels).
_SAFE_SLOT_RE = re.compile(r'^[A-Za-z0-9_/\.\-: ]{0,200}$')

# Intent → which generator handles it (also validates intent names)
INTENT_TO_SCHEMA: Dict[str, Dict[str, Any]] = {
    intent: {"primary_label": info.get("primary_node", "Node")}
    for intent, info in CAPABILITY_MAP.items()
    if intent != "unknown_intent"
}


# ---------------------------------------------------------------------------
# Template Matcher — Tier 1 (zero latency)
# ---------------------------------------------------------------------------

class TemplateMatcher:
    """
    Matches a QueryEntry.id against registered hardcoded Cypher templates.
    Templates may use {slot_name} Python format placeholders.
    """

    def __init__(self, templates: Dict[str, str]) -> None:
        self._templates: Dict[str, str] = dict(templates)

    def match(
        self,
        query_entry: QueryEntry,
        slots: Dict[str, Any],
    ) -> Optional[str]:
        template = self._templates.get(query_entry["id"])
        if template is None:
            return None
        # Validate slot values before string-formatting into Cypher to prevent
        # Cypher injection via user-controlled slot content.
        for slot_key, slot_val in slots.items():
            if isinstance(slot_val, str) and not _SAFE_SLOT_RE.match(slot_val):
                bad_chars = {c for c in slot_val if not re.match(r'[A-Za-z0-9_/.\-: ]', c)}
                raise ValueError(
                    f"Slot '{slot_key}' contains unsafe characters {bad_chars!r}. "
                    "Only alphanumeric characters, underscores, hyphens, slashes, "
                    "dots, colons, and spaces are permitted."
                )
        try:
            return template.format_map(_SlotProxy(slots))
        except KeyError as exc:
            raise RuntimeError(
                f"Template '{query_entry['id']}' references slot {exc} "
                f"absent from intent slots: {list(slots.keys())}"
            ) from exc


class _SlotProxy(dict):
    """Returns the placeholder unchanged for missing keys."""
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


# ---------------------------------------------------------------------------
# Schema Generator — Tier 4 (deterministic fallback)
# ---------------------------------------------------------------------------

class SchemaGenerator:
    """
    Generates verified read-only Cypher grounded in schema_context.py.

    Each intent has a dedicated generator that returns a GeneratorResult
    (cypher + reasoning).  The reasoning string is the human-readable
    description of which graph pattern was chosen and why — it becomes
    TraceStep.intent so the LLM explainer sees real context.
    """

    def generate(
        self,
        query_entry: QueryEntry,
        intent: Dict[str, Any],
    ) -> GeneratorResult:
        intent_type: str       = intent.get("intent_type", "unknown_intent")
        slots:       Dict      = intent.get("slots", {})
        keywords:    List[str] = intent.get("keywords", [])
        operation:   str       = query_entry.get("operation", "list")

        if intent_type not in INTENT_TO_SCHEMA:
            raise NotImplementedError(
                f"[SchemaGenerator] No generation rule for intent '{intent_type}'.\n"
                f"Known intents: {list(INTENT_TO_SCHEMA.keys())}\n"
                f"Query entry id: '{query_entry['id']}'\n"
                f"Add a template to CYPHER_TEMPLATES in cli.py or a rule to "
                f"INTENT_TO_SCHEMA in hybrid_optimizer.py."
            )

        fn = _GENERATORS.get(intent_type, _generic)
        return fn(operation, slots, keywords, intent.get("pid_id", "UNKNOWN"))


# ===========================================================================
# Per-intent Cypher generators — each returns GeneratorResult(cypher, reasoning)
# ===========================================================================
# Property reference:
#   Node      : id, label, structural_type, bbox, xmin, xmax, ymin, ymax, source
#   (Equipment node removed — use Node WHERE label IN ['valve','tank','instrumentation','general'])
#   PipeSegment : id, segment_status, node_count, component_id, geometry_hash
#   LogicalPipeSegment : id, flow_state, flow_direction, flow_confidence,
#                        flow_source, endpoints, trace_nodes, via, length
#   Annotation  : id, label, type, intent, pattern_type, rarity_score,
#                 node_id, lps_id, ps_id, degree, ...
#   Arrow       : id  (no direction property — direction via FLOW_EVIDENCE rel)
#   Evidence    : id, observed_direction, direction_hint, confidence,
#                 cosine_alignment, low_confidence, normalized
#   PID         : pid_id, graphml_path, image_path
#   Skid        : skid_id, skid_type
#   Plant       : plant_id
# ===========================================================================


def _engineering_inventory(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    t = set(kw)
    pid_n = _pid("n", pid_id)

    # ── Inferred equipment types (check valve, inline equipment, pump) ─────
    # These have special label values: inferred_check_valve, inferred_inline_equipment,
    # or functional_label='pump' on tank nodes.  Must check before the generic loop.
    _is_check_valve = bool(t & {"check"} and t & {"valve", "valves"})
    _is_inline      = bool(t & {"inline"} and t & {"equipment"})
    _is_pump        = bool(t & {"pump", "pumps"})
    _is_strainer    = bool(t & {"strainer", "strainers"})

    if _is_check_valve:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (n:Node)\n"
                    f"WHERE n.label = 'inferred_check_valve'{pid_n}\n"
                    "RETURN n.label AS type, count(n) AS total"
                ),
                reasoning="Counted inferred check valve symbols on the drawing.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.label = 'inferred_check_valve'{pid_n}\n"
                "OPTIONAL MATCH (n)-[:PIPE]-(nb:Node)\n"
                "WHERE nb.label <> 'background'\n"
                "RETURN n.id AS node_id, n.label AS type,\n"
                "       collect(DISTINCT nb.id)[0..4] AS connected_to,\n"
                "       collect(DISTINCT nb.label)[0..4] AS neighbour_types\n"
                f"ORDER BY n.id\nLIMIT {_limit(slots, 100)}"
            ),
            reasoning="Listed inferred check valve symbols with their pipe connections.",
        )

    if _is_inline:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (n:Node)\n"
                    f"WHERE n.label = 'inferred_inline_equipment'{pid_n}\n"
                    "RETURN n.label AS type, count(n) AS total"
                ),
                reasoning="Counted inferred inline equipment symbols on the drawing.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.label = 'inferred_inline_equipment'{pid_n}\n"
                "OPTIONAL MATCH (n)-[:PIPE]-(nb:Node)\n"
                "WHERE nb.label <> 'background'\n"
                "RETURN n.id AS node_id, n.label AS type,\n"
                "       collect(DISTINCT nb.id)[0..4] AS connected_to,\n"
                "       collect(DISTINCT nb.label)[0..4] AS neighbour_types\n"
                f"ORDER BY n.id\nLIMIT {_limit(slots, 100)}"
            ),
            reasoning="Listed inferred inline equipment symbols with their pipe connections.",
        )

    if _is_pump:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (n:Node)\n"
                    f"WHERE n.label = 'tank' AND n.functional_label = 'pump'{pid_n}\n"
                    "RETURN 'pump' AS type, count(n) AS total"
                ),
                reasoning="Counted pump units on the drawing (tank nodes with functional_label='pump').",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.label = 'tank' AND n.functional_label = 'pump'{pid_n}\n"
                "OPTIONAL MATCH (n)-[:PIPE]-(nb:Node)\n"
                "WHERE nb.label <> 'background'\n"
                "RETURN n.id AS node_id, 'pump' AS type,\n"
                "       collect(DISTINCT nb.id)[0..4] AS connected_to,\n"
                "       collect(DISTINCT nb.label)[0..4] AS neighbour_types\n"
                f"ORDER BY n.id\nLIMIT {_limit(slots, 100)}"
            ),
            reasoning="Listed pump units with their pipe connections (tank nodes with functional_label='pump').",
        )

    if _is_strainer:
        # No dedicated strainer nodes — show missing_suction_strainer violations
        return GeneratorResult(
            cypher=(
                "MATCH (a:Annotation)\n"
                f"WHERE a.type = 'engineering_rule_violation'{_pid('a', pid_id)}\n"
                "  AND a.pattern_type = 'missing_suction_strainer'\n"
                "RETURN a.target_id AS equipment_id,\n"
                "       a.severity AS severity,\n"
                "       a.explanation AS explanation\n"
                f"ORDER BY a.severity\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning="Listed equipment flagged for missing suction strainers from engineering rule violations.",
        )

    if op == "count":
        for eq_type in ("valve", "tank", "instrumentation", "arrow", "crossing", "general"):
            if eq_type in t or f"{eq_type}s" in t:
                return GeneratorResult(
                    cypher=(
                        f"MATCH (n:Node)\n"
                        f"WHERE n.label = '{eq_type}'{pid_n}\n"
                        "RETURN n.label AS type, count(n) AS total"
                    ),
                    reasoning=f"Counted {eq_type} symbols on the drawing.",
                )
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.structural_type = 'SYMBOL'{pid_n}\n"
                "  AND n.label <> 'background'\n"
                "  AND n.label <> 'connector'\n"
                "RETURN n.label AS type, count(n) AS total\n"
                "ORDER BY total DESC"
            ),
            reasoning="Counted all equipment symbols on the drawing, grouped by type.",
        )

    label_filter = ""
    label_desc   = ""
    for eq_type in ("valve", "tank", "instrumentation", "general"):
        if eq_type in t or f"{eq_type}s" in t:
            label_filter = f'\nAND n.label = "{eq_type}"'
            label_desc   = f", filtered to label='{eq_type}'"
            break

    return GeneratorResult(
        cypher=(
            "MATCH (n:Node)\n"
            f"WHERE n.structural_type = 'SYMBOL'{pid_n}\n"
            f"  AND n.label <> 'background'\n"
            f"  AND n.label <> 'connector'{label_filter}\n"
            "RETURN n.id AS node_id, n.label AS type,\n"
            "       n.structural_type AS structural_type\n"
            f"ORDER BY n.label\nLIMIT {_limit(slots, 100)}"
        ),
        reasoning=f"Listed all equipment symbols on the drawing{label_desc}.",
    )


def _valve_placement(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    t         = set(kw)
    pid_n     = _pid("n", pid_id)
    node_id   = _safe_id(slots.get("tag"))
    id_filter = f'\nAND n.id = "{node_id}"' if node_id else ""

    # ── Check valve queries ───────────────────────────────────────────────
    # "check" + "valve"/"valves" → label='inferred_check_valve'
    # "where are check valves?" / "show all check valves" / "how many check valves?"
    if t & {"check"} and t & {"valve", "valves"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (n:Node)\n"
                    f"WHERE n.label = 'inferred_check_valve'{pid_n}\n"
                    "RETURN count(n) AS total_check_valves"
                ),
                reasoning="Counted inferred check valve symbols on the drawing.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.label = 'inferred_check_valve'{pid_n}\n"
                "OPTIONAL MATCH (n)-[:PIPE]-(nb:Node)\n"
                "WHERE nb.label <> 'background'\n"
                "RETURN n.id AS valve_id,\n"
                "       n.label AS valve_type,\n"
                "       collect(DISTINCT nb.id)[0..4] AS connected_to,\n"
                "       collect(DISTINCT nb.label)[0..4] AS neighbour_types\n"
                f"ORDER BY n.id\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning="Listed inferred check valve symbols with their pipe connections.",
        )

    # ── All valve types combined (check + regular) ────────────────────────
    # "what types of valves?" / "show valve types" / "valve type breakdown"
    if t & {"type", "types", "breakdown", "kind", "kinds"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (n:Node)\n"
                    f"WHERE n.label IN ['valve', 'inferred_check_valve']{pid_n}\n"
                    "RETURN n.label AS valve_type, count(n) AS total\n"
                    "ORDER BY total DESC"
                ),
                reasoning="Counted valves grouped by type (manual valves vs inferred check valves).",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.label IN ['valve', 'inferred_check_valve']{pid_n}\n"
                "RETURN n.label AS valve_type, count(n) AS total\n"
                "ORDER BY total DESC"
            ),
            reasoning="Listed valve type breakdown (manual valves vs inferred check valves).",
        )

    # ── Valves filtered by their LPS flow state ───────────────────────────
    # "valves on segments with unknown flow" / "valves on seeded/propagated segments"
    if t & {"seeded", "propagated", "unknown", "flow", "direction"} and        t & {"segment", "segments", "pipe", "pipes", "lps", "logical"}:
        if "unknown" in t:
            flow_filter = "lps.flow_state = 'UNKNOWN'"
            flow_label  = "UNKNOWN"
        elif t & {"seeded", "propagated"}:
            flow_filter = "lps.flow_state IN ['SEEDED', 'PROPAGATED']"
            flow_label  = "SEEDED or PROPAGATED"
        else:
            flow_filter = "lps.flow_state IS NOT NULL"
            flow_label  = "any known"
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (n:Node)\n"
                    f"WHERE n.label = 'valve'{pid_n}\n"
                    "MATCH (n)<-[:CONTAINS]-(ps:PipeSegment)<-[:COVERS]-(lps:LogicalPipeSegment)\n"
                    f"WHERE {flow_filter}\n"
                    "RETURN count(DISTINCT n) AS valves_on_flow_filtered_segments"
                ),
                reasoning=f"Counted valves on pipe lines with {flow_label} flow direction.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.label = 'valve'{pid_n}\n"
                "MATCH (n)<-[:CONTAINS]-(ps:PipeSegment)<-[:COVERS]-(lps:LogicalPipeSegment)\n"
                f"WHERE {flow_filter}\n"
                "RETURN DISTINCT n.id AS valve_id,\n"
                "       lps.id AS logical_segment,\n"
                "       lps.flow_state AS flow_state,\n"
                "       lps.flow_direction AS flow_direction\n"
                f"ORDER BY n.id\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning=f"Listed valves on pipe lines with {flow_label} flow direction.",
        )

    # ── Valves filtered by pipe degree (connections count) ────────────────
    # "high-degree valves", "valves with many connections", "junction valves"
    if t & {"degree", "junction", "multi", "connections", "many", "high"}:
        deg_threshold = 3  # default: 3+ PIPE edges = junction point
        for n_val in slots.get("numbers", []):
            try:
                deg_threshold = int(n_val)
                break
            except (ValueError, TypeError):
                pass
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (n:Node)\n"
                    f"WHERE n.label = 'valve'{pid_n}\n"
                    "WITH n, size([(n)-[:PIPE]-(m:Node) | m]) AS deg\n"
                    f"WHERE deg >= {deg_threshold}\n"
                    "RETURN count(n) AS high_degree_valves"
                ),
                reasoning=f"Counted valves with {deg_threshold} or more pipe connections.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.label = 'valve'{pid_n}\n"
                "WITH n, size([(n)-[:PIPE]-(m:Node) | m]) AS deg\n"
                f"WHERE deg >= {deg_threshold}\n"
                "RETURN n.id AS valve_id, deg AS pipe_connections\n"
                f"ORDER BY deg DESC\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning=(
                f"Listed valves with {deg_threshold} or more pipe connections, ordered by connection count."
            ),
        )

    if op == "count":
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.label = 'valve'{pid_n}{id_filter}\n"
                "RETURN count(n) AS total_valves"
            ),
            reasoning="Counted valve symbols on the drawing.",
        )

    return GeneratorResult(
        cypher=(
            "MATCH (n:Node)\n"
            f"WHERE n.label = 'valve'{pid_n}{id_filter}\n"
            "OPTIONAL MATCH (n)-[:PIPE]-(nb:Node)\n"
            "WHERE nb.label <> 'background'\n"
            "RETURN n.id AS valve_id,\n"
            "       n.structural_type AS structural_type,\n"
            "       collect(DISTINCT nb.id)[0..4] AS connected_to,\n"
            "       collect(DISTINCT nb.label)[0..4] AS neighbour_types\n"
            f"ORDER BY n.id\nLIMIT {_limit(slots, 50)}"
        ),
        reasoning="Listed valves with their directly connected equipment and pipe symbols.",
    )


def _instrument_attachment(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    t         = set(kw)
    pid_n = _pid("n", pid_id)
    pid_a = _pid("a", pid_id)
    node_id   = _safe_id(slots.get("tag"))
    id_filter = f' AND n.id = "{node_id}"' if node_id else ""

    # ── Instruments filtered by their LPS flow state ─────────────────────
    # "instruments on segments with unknown flow" / "instruments on confirmed segments"
    if t & {"seeded", "propagated", "unknown", "flow", "direction"} and        t & {"segment", "segments", "pipe", "pipes", "lps", "logical"}:
        if "unknown" in t:
            flow_filter = "lps.flow_state = 'UNKNOWN'"
            flow_label  = "UNKNOWN"
        elif t & {"seeded", "propagated"}:
            flow_filter = "lps.flow_state IN ['SEEDED', 'PROPAGATED']"
            flow_label  = "SEEDED or PROPAGATED"
        else:
            flow_filter = "lps.flow_state IS NOT NULL"
            flow_label  = "any known"
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (n:Node)\n"
                    f"WHERE n.label = 'instrumentation'{pid_n}\n"
                    "MATCH (n)<-[:CONTAINS]-(ps:PipeSegment)<-[:COVERS]-(lps:LogicalPipeSegment)\n"
                    f"WHERE {flow_filter}\n"
                    "RETURN count(DISTINCT n) AS instruments_on_flow_filtered_segments"
                ),
                reasoning=f"Counted instruments on pipe lines with {flow_label} flow direction.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.label = 'instrumentation'{pid_n}\n"
                "MATCH (n)<-[:CONTAINS]-(ps:PipeSegment)<-[:COVERS]-(lps:LogicalPipeSegment)\n"
                f"WHERE {flow_filter}\n"
                "RETURN DISTINCT n.id AS node_id,\n"
                "       lps.id AS logical_segment,\n"
                "       lps.flow_state AS flow_state,\n"
                "       lps.flow_direction AS flow_direction\n"
                f"ORDER BY n.id\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning=f"Listed instruments on pipe lines with {flow_label} flow direction.",
        )

    if t & {"orphan", "orphaned", "unattached", "missing", "floating", "detached"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (a:Annotation)-[:ANNOTATES]->(n:Node)\n"
                    f"WHERE a.type = 'orphan_node'{pid_a}\n"
                    "  AND n.label = 'instrumentation'\n"
                    "RETURN count(DISTINCT n) AS orphaned_instruments"
                ),
                reasoning="Counted orphaned instruments with no pipe connections.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (a:Annotation)-[:ANNOTATES]->(n:Node)\n"
                f"WHERE a.type = 'orphan_node'{pid_a}\n"
                "  AND n.label = 'instrumentation'\n"
                "RETURN n.id AS node_id, n.label AS type,\n"
                "       a.type AS issue, a.rarity_score AS rarity\n"
                f"ORDER BY a.rarity_score DESC\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning="Listed orphaned instruments with no pipe connections.",
        )

    if op == "count":
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.label = 'instrumentation'{pid_n}{id_filter}\n"
                "RETURN count(n) AS total_instruments"
            ),
            reasoning="Counted instrument symbols on the drawing.",
        )

    return GeneratorResult(
        cypher=(
            "MATCH (n:Node)\n"
            f"WHERE n.label = 'instrumentation'{pid_n}{id_filter}\n"
            "OPTIONAL MATCH (ps:PipeSegment)-[:CONTAINS]->(n)\n"
            "OPTIONAL MATCH (lps:LogicalPipeSegment)-[:COVERS]->(ps)\n"
            "RETURN n.id AS node_id,\n"
            "       collect(DISTINCT ps.id)[0..3] AS pipe_segments,\n"
            "       collect(DISTINCT lps.id)[0..3] AS logical_segments\n"
            f"ORDER BY n.id\nLIMIT {_limit(slots, 50)}"
        ),
        reasoning="Listed instruments with their pipe run and pipe line context.",
    )


def _line_attributes(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    t      = set(kw)
    seg_id = _safe_id(slots.get("tag"))
    use_lps = bool(t & {"flow", "direction", "logical", "lps", "annotated"})
    pid_lps = _pid("lps", pid_id)
    pid_ps  = _pid("ps", pid_id)

    if use_lps:
        id_filter = f'WHERE lps.id = "{seg_id}"' if seg_id else f"WHERE 1=1"
        extra     = pid_lps
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (lps:LogicalPipeSegment)\n"
                    f"{id_filter}{extra}\n"
                    "RETURN count(lps) AS total_logical_segments"
                ),
                reasoning="Counted pipe lines on the drawing.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (lps:LogicalPipeSegment)\n"
                f"{id_filter}{extra}\n"
                "RETURN lps.id AS segment_id,\n"
                "       lps.flow_state AS flow_state,\n"
                "       lps.flow_direction AS flow_direction,\n"
                "       lps.flow_confidence AS confidence,\n"
                "       lps.length AS length\n"
                f"ORDER BY lps.id\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning="Listed pipe lines with their flow direction, confidence score, and length.",
        )

    id_filter = f'WHERE ps.id = "{seg_id}"' if seg_id else f"WHERE 1=1"
    extra     = pid_ps
    if op == "count":
        return GeneratorResult(
            cypher=(
                "MATCH (ps:PipeSegment)\n"
                f"{id_filter}{extra}\n"
                "RETURN count(ps) AS total_pipe_segments"
            ),
            reasoning="Counted pipe runs on the drawing.",
        )
    return GeneratorResult(
        cypher=(
            "MATCH (ps:PipeSegment)\n"
            f"{id_filter}{extra}\n"
            "OPTIONAL MATCH (lps:LogicalPipeSegment)-[:COVERS]->(ps)\n"
            "RETURN ps.id AS segment_id,\n"
            "       ps.node_count AS node_count,\n"
            "       ps.segment_status AS status,\n"
            "       ps.component_id AS component,\n"
            "       lps.id AS logical_segment\n"
            f"ORDER BY ps.id\nLIMIT {_limit(slots, 50)}"
        ),
        reasoning="Listed pipe runs with their node count, status, and associated pipe line.",
    )


def _connectivity_topology(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    t       = set(kw)
    pid_n   = _pid("n", pid_id)
    node_id = _safe_id(slots.get("tag"))

    if t & {"path", "between", "route", "reach"}:
        # Support "path between tank67 and valve12" via slots.node_ids
        node_ids = [_safe_id(x) for x in slots.get("node_ids", []) if _safe_id(x)]
        start = node_ids[0] if len(node_ids) >= 1 else (node_id or "START_NODE_ID")
        end_filter = ""
        end_desc   = "reachable equipment symbols"
        if len(node_ids) >= 2:
            end_filter = f'\n  AND end.id = "{node_ids[1]}"'
            end_desc   = f"'{node_ids[1]}'"
        pid_start = _pid("start", pid_id)
        return GeneratorResult(
            cypher=(
                f'MATCH (start:Node {{id: "{start}"}})\n'
                f"WHERE 1=1{pid_start}\n"
                "MATCH path = (start)-[:PIPE*1..12]-(end:Node)\n"
                "WHERE end <> start\n"
                "  AND end.label <> 'background'\n"
                f"  AND end.structural_type = 'SYMBOL'{end_filter}\n"
                "RETURN [n IN nodes(path) | n.id] AS path_nodes,\n"
                "       [n IN nodes(path) | n.label] AS path_labels,\n"
                f"       length(path) AS hops\n"
                f"ORDER BY hops\nLIMIT {_limit(slots, 20)}"
            ),
            reasoning=(
                f"Traced all pipe connections from '{start}' to find {end_desc}."
            ),
        )

    if t & {"upstream", "downstream"}:
        is_downstream = "downstream" in t
        start         = node_id or "START_NODE_ID"
        dir_label     = "downstream" if is_downstream else "upstream"
        # Flow exits start when:
        #   FORWARD + lps starts with start.id  (start is natural-first, flow goes start→other)
        #   REVERSE + lps ends   with start.id  (start is natural-last,  flow goes start→first)
        # Flow enters start when the opposite holds (upstream direction).
        if is_downstream:
            dir_filter = (
                f"  AND (\n"
                f"    (lps0.flow_direction = 'FORWARD' AND lps0.id STARTS WITH '{start}__')\n"
                f"    OR\n"
                f"    (lps0.flow_direction = 'REVERSE' AND lps0.id ENDS WITH '__{start}')\n"
                f"  )\n"
            )
        else:
            dir_filter = (
                f"  AND (\n"
                f"    (lps0.flow_direction = 'FORWARD' AND lps0.id ENDS WITH '__{start}')\n"
                f"    OR\n"
                f"    (lps0.flow_direction = 'REVERSE' AND lps0.id STARTS WITH '{start}__')\n"
                f"  )\n"
            )
        return GeneratorResult(
            cypher=(
                f'MATCH (start:Node {{id: "{start}", pid_id: $pid_id}})-[:ENDPOINT_OF]->(lps0:LogicalPipeSegment)\n'
                f"WHERE lps0.flow_state IN ['SEEDED','PROPAGATED']\n"
                f"{dir_filter}"
                "MATCH (lps0)-[:ADJACENT_VIA_NODES*0..8]-(lps:LogicalPipeSegment)\n"
                "WHERE lps.flow_state IN ['SEEDED','PROPAGATED']\n"
                "MATCH (far:Node)-[:ENDPOINT_OF]->(lps)\n"
                "WHERE far.id <> start.id\n"
                "  AND far.structural_type = 'SYMBOL'\n"
                "  AND NOT far.label IN ['crossing','arrow']\n"
                "WITH far.id AS node_id, far.label AS type,\n"
                "     min(lps.id) AS via_segment,\n"
                "     min(lps.flow_state) AS flow_state,\n"
                "     min(lps.flow_confidence) AS confidence\n"
                "RETURN node_id, type, via_segment, flow_state, confidence\n"
                f"ORDER BY type, node_id\n"
                f"LIMIT {_limit(slots, 50)}"
            ),
            reasoning=(
                f"Traced all {dir_label} flow paths from '{start}', "
                f"following connected pipe segments to list equipment along the full flow path."
            ),
        )

    if node_id:
        # Determine optional label filter — e.g. "what valves are connected to tank1?"
        # extracts label='valve' so only valve-type SYMBOL nodes are returned.
        _neighbour_label = ""
        _neighbour_desc  = "equipment symbols"
        if t & {"valve", "valves", "cv", "pv", "hv", "sdv", "psv", "prv", "bv",
                "gate", "gates", "globe", "ball", "butterfly", "check"}:
            _neighbour_label = "\n  AND nb.label = 'valve'"
            _neighbour_desc  = "valves"
        elif t & {"instrument", "instruments", "instrumentation",
                  "pi", "ft", "lt", "pt", "fit", "lic", "pic", "tic"}:
            _neighbour_label = "\n  AND nb.label = 'instrumentation'"
            _neighbour_desc  = "instruments"
        elif t & {"tank", "tanks", "vessel", "vessels", "pump", "pumps",
                  "equipment", "compressor", "compressors"}:
            _neighbour_label = "\n  AND nb.label = 'tank'"
            _neighbour_desc  = "tanks/vessels"

        # Use multi-hop traversal to skip through intermediate connector nodes.
        # A direct 1-hop [:PIPE] query returns connector nodes (structural_type='CONNECTOR')
        # rather than actual equipment.  Traverse up to 12 hops and filter to SYMBOL nodes.
        if op == "count":
            return GeneratorResult(
                cypher=(
                    f'MATCH (n:Node {{id: "{node_id}"}})-[:PIPE*1..12]-(nb:Node)\n'
                    f"WHERE nb.structural_type = 'SYMBOL'\n"
                    f"  AND nb.label <> 'background'\n"
                    f"  AND nb.id <> '{node_id}'{_neighbour_label}\n"
                    f"RETURN count(DISTINCT nb) AS neighbour_count"
                ),
                reasoning=f"Counted {_neighbour_desc} reachable from '{node_id}' via pipe (skipping connector nodes).",
            )
        return GeneratorResult(
            cypher=(
                f'MATCH (n:Node {{id: "{node_id}"}})-[:PIPE*1..12]-(nb:Node)\n'
                f"WHERE nb.structural_type = 'SYMBOL'\n"
                f"  AND nb.label <> 'background'\n"
                f"  AND nb.id <> '{node_id}'{_neighbour_label}\n"
                f"RETURN DISTINCT nb.id AS neighbour_id, nb.label AS type\n"
                f"ORDER BY nb.label, nb.id\n"
                f"LIMIT {_limit(slots, 50)}"
            ),
            reasoning=f"Listed {_neighbour_desc} reachable from '{node_id}' via pipe connections (traversing through connectors to reach actual equipment).",
        )

    if op == "count":
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)-[:PIPE]-(m:Node)\n"
                "WHERE n.label <> 'background'\n"
                "RETURN count(DISTINCT n) AS connected_nodes"
            ),
            reasoning="Counted all connected equipment symbols on the drawing.",
        )
    return GeneratorResult(
        cypher=(
            "MATCH (n:Node)-[:PIPE]-(m:Node)\n"
            f"WHERE n.structural_type = 'SYMBOL'{pid_n}\n"
            "  AND n.label <> 'background'\n"
            "WITH n, size([(n)-[:PIPE]-(x:Node) | x]) AS deg\n"
            "RETURN n.id AS node_id, n.label AS type, deg AS connections\n"
            f"ORDER BY deg DESC\nLIMIT {_limit(slots, 50)}"
        ),
        reasoning="Listed all equipment symbols ordered by number of pipe connections.",
    )


def _external_interfaces(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    t = set(kw)
    pid_n = _pid("n", pid_id)

    side_filter = ""
    side_desc   = ""
    if t & {"left", "west"}:
        side_filter = "\n  AND n.xmin < 500"
        side_desc   = " on the left side of the drawing"
    elif t & {"right", "east"}:
        side_filter = "\n  AND n.xmin > 1500"
        side_desc   = " on the right side of the drawing"

    if op == "count":
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.label = 'inlet/outlet'{pid_n}{side_filter}\n"
                "RETURN count(n) AS total_interfaces"
            ),
            reasoning=f"Counted external interface points{side_desc} on the drawing.",
        )

    return GeneratorResult(
        cypher=(
            "MATCH (n:Node)\n"
            f"WHERE n.label = 'inlet/outlet'{pid_n}{side_filter}\n"
            "OPTIONAL MATCH (n)-[:PIPE]-(conn:Node)\n"
            "WHERE conn.label = 'connector'\n"
            "OPTIONAL MATCH (conn)-[:PIPE]-(nb:Node)\n"
            "WHERE nb.id <> n.id AND nb.label <> 'background'\n"
            "RETURN n.id AS interface_id,\n"
            "       n.xmin AS x_pos,\n"
            "       conn.id AS connector_id,\n"
            "       collect(DISTINCT nb.id)[0..3] AS connects_to,\n"
            "       collect(DISTINCT nb.label)[0..3] AS connects_to_types\n"
            f"ORDER BY n.xmin\nLIMIT {_limit(slots, 50)}"
        ),
        reasoning=f"Listed external interface points{side_desc} with their connected equipment.",
    )


def _redundancy_patterns(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    t = set(kw)
    pid_a   = _pid("a", pid_id)
    pid_ps  = _pid("ps", pid_id)

    # ── Duplicate / identical pipe segments ──────────────────────────────
    # 'duplicate_symbol_candidate' and 'identical_ps_neighborhood' do NOT exist
    # in the live DB.  Use geometry_hash grouping on PipeSegment for true
    # geometric duplicates; structural_pattern_rarity / rare_motif_local for
    # unusual topology.
    if t & {"duplicate", "identical", "copy"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (ps:PipeSegment)\n"
                    f"WHERE 1=1{pid_ps}\n"
                    "  AND ps.geometry_hash IS NOT NULL\n"
                    "WITH ps.geometry_hash AS hash, count(ps) AS cnt\n"
                    "WHERE cnt > 1\n"
                    "RETURN count(hash) AS duplicate_hash_groups,\n"
                    "       sum(cnt) AS total_segments_involved"
                ),
                reasoning="Counted groups of geometrically identical pipe runs on the drawing.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (ps:PipeSegment)\n"
                f"WHERE 1=1{pid_ps}\n"
                "  AND ps.geometry_hash IS NOT NULL\n"
                "WITH ps.geometry_hash AS hash, collect(ps.id) AS segment_ids,\n"
                "     count(ps) AS cnt\n"
                "WHERE cnt > 1\n"
                "RETURN hash AS geometry_hash, cnt AS count, segment_ids\n"
                f"ORDER BY cnt DESC\nLIMIT {_limit(slots, 30)}"
            ),
            reasoning="Listed groups of geometrically identical pipe runs, ordered by group size.",
        )

    # ── Parallel / adjacent / bypass paths ───────────────────────────────
    if t & {"parallel", "adjacent", "bypass"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (ps1:PipeSegment)-[adj:ADJACENT_VIA_NODES]->(ps2:PipeSegment)\n"
                    "RETURN count(adj) AS total_adjacent_pairs"
                ),
                reasoning="Counted adjacent pipe run pairs on the drawing.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (ps1:PipeSegment)-[adj:ADJACENT_VIA_NODES]->(ps2:PipeSegment)\n"
                "RETURN ps1.id AS segment_a, ps2.id AS segment_b,\n"
                "       adj.via_count AS shared_nodes\n"
                f"ORDER BY adj.via_count DESC\nLIMIT {_limit(slots, 30)}"
            ),
            reasoning=(
                "Listed adjacent pipe run pairs, ordered by number of shared connection points."
            ),
        )

    # ── Default: rare / unusual structural patterns ───────────────────────
    # structural_pattern_rarity and rare_motif_local are the confirmed real types.
    if op == "count":
        return GeneratorResult(
            cypher=(
                "MATCH (a:Annotation)\n"
                f"WHERE a.type IN ['structural_pattern_rarity', 'rare_motif_local']{pid_a}\n"
                "RETURN a.type AS pattern, count(a) AS total\n"
                "ORDER BY total DESC"
            ),
            reasoning="Counted pre-analysed unusual topology patterns on the drawing, grouped by type.",
        )
    return GeneratorResult(
        cypher=(
            "MATCH (a:Annotation)\n"
            f"WHERE a.type IN ['structural_pattern_rarity', 'rare_motif_local']{pid_a}\n"
            "OPTIONAL MATCH (a)-[:ANNOTATES]->(target)\n"
            "RETURN a.type AS pattern_type, a.rarity_score AS rarity,\n"
            "       coalesce(target.id, '') AS target_id\n"
            f"ORDER BY a.rarity_score DESC\nLIMIT {_limit(slots, 50)}"
        ),
        reasoning="Listed pre-analysed unusual topology patterns, ordered by rarity.",
    )


def _drawing_consistency(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    """
    Pre-computed quality checks via Annotation.type.

    RULE 9 from schema: Quality issues are PRE-COMPUTED as Annotation nodes.
    Always query Annotation.type first — do not recompute structural checks.

    Annotation.type → meaning:
      'orphan_node'                      → isolated node with no connections
      'pipe_segment_no_logical_mapping'  → PS not covered by any LPS
      'endpoint_count_mismatch'          → PS has wrong number of endpoints
      'logical_missing_endpoints'        → LPS has no endpoint nodes
      'direction_conflict_observed'      → LPS has conflicting flow arrows
      'logical_no_evidence'              → LPS has no flow evidence at all
      'pipe_segment_no_evidence_via_lps' → PS unreachable via LPS flow evidence
      'structural_pattern_rarity'         → unusual topology rarity score
      'structural_high_degree'           → node has unusually high degree
      'direction_evidence_missing'       → PS missing flow direction evidence

    Dangling ends / dead legs: 'orphan_node' OR degree-based filter.
    Junctions / T-pieces: degree >= 3 via list comprehension.
    """
    t     = set(kw)
    pid_n = _pid("n", pid_id)
    pid_a = _pid("a", pid_id)
    pid_ps = _pid("ps", pid_id)

    # ── Dangling ends / dead legs ─────────────────────────────────────────
    if t & {"dangling", "dead", "deadleg", "terminus", "stub", "blind",
            "open-end", "openend", "end", "deadend"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (n:Node)\n"
                    f"WHERE n.structural_type = 'SYMBOL'{pid_n}\n"
                    "  AND n.label <> 'background'\n"
                    "WITH n, size([(n)-[:PIPE]-(m:Node) | m]) AS deg\n"
                    "WHERE deg = 1\n"
                    "RETURN count(n) AS dangling_ends"
                ),
                reasoning="Counted symbols connected to only one pipe run (dangling ends).",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.structural_type = 'SYMBOL'{pid_n}\n"
                "  AND n.label <> 'background'\n"
                "WITH n, size([(n)-[:PIPE]-(m:Node) | m]) AS deg\n"
                "WHERE deg = 1\n"
                "RETURN n.id AS node_id, n.label AS type, deg AS connections\n"
                f"ORDER BY n.id\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning="Listed symbols connected to only one pipe run (dangling ends).",
        )

    # ── Orphaned / isolated nodes (pre-computed) ──────────────────────────
    if t & {"orphan", "orphaned", "isolated", "disconnected", "floating",
            "unconnected"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (a:Annotation)-[:ANNOTATES]->(n:Node)\n"
                    f"WHERE a.type = 'orphan_node'{pid_a}\n"
                    "  AND NOT n.label IN ['arrow', 'crossing', 'background']\n"
                    "RETURN count(a) AS total_orphan_nodes"
                ),
                reasoning="Counted pre-analysed orphaned symbols with no pipe connections.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (a:Annotation)-[:ANNOTATES]->(n:Node)\n"
                f"WHERE a.type = 'orphan_node'{pid_a}\n"
                "  AND NOT n.label IN ['arrow', 'crossing', 'background']\n"
                "RETURN n.id AS node_id, n.label AS type,\n"
                "       a.rarity_score AS rarity\n"
                f"ORDER BY a.rarity_score DESC\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning="Listed pre-analysed orphaned symbols with no pipe connections.",
        )

    # ── Pipe segments without logical mapping (pre-computed) ──────────────
    if t & {"unmapped", "uncovered", "disconnected"} and t & {"segment", "pipe"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (a:Annotation)\n"
                    f"WHERE a.type = 'pipe_segment_no_logical_mapping'{pid_a}\n"
                    "RETURN count(a) AS total_unmapped_segments"
                ),
                reasoning="Counted pipe runs with no associated pipe line.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (a:Annotation)-[:ANNOTATES]->(ps:PipeSegment)\n"
                f"WHERE a.type = 'pipe_segment_no_logical_mapping'{pid_a}\n"
                "RETURN ps.id AS segment_id,\n"
                "       ps.node_count AS node_count,\n"
                "       a.rarity_score AS rarity\n"
                f"ORDER BY ps.id\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning="Listed pipe runs that have not been mapped to a pipe line.",
        )

    # ── Flow direction issues (pre-computed) ──────────────────────────────
    if t & {"conflict", "conflicting", "contradicting", "ambiguous",
            "low", "uncertain", "confidence"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (a:Annotation)\n"
                    f"WHERE a.type = 'lps_low_confidence_evidence'{pid_a}\n"
                    "RETURN a.type AS issue, count(a) AS total\n"
                    "ORDER BY total DESC"
                ),
                reasoning="Counted pipe lines with low-confidence flow direction.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (a:Annotation)-[:ANNOTATES]->(target)\n"
                f"WHERE a.type = 'lps_low_confidence_evidence'{pid_a}\n"
                "RETURN a.type AS issue, coalesce(target.id, '') AS target_id,\n"
                "       a.rarity_score AS rarity\n"
                f"ORDER BY a.rarity_score DESC\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning="Listed pipe lines with low-confidence flow direction.",
        )

    # ── Missing flow evidence (direct LPS query) ──────────────────────────
    if t & {"missing", "no-evidence", "evidence", "unannotated"}:
        pid_lps = _pid("lps", pid_id)
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (lps:LogicalPipeSegment)\n"
                    f"WHERE lps.flow_state = 'UNKNOWN'{pid_lps}\n"
                    "RETURN 'no_flow_resolved' AS issue, count(lps) AS total"
                ),
                reasoning="Counted pipe lines with no resolved flow direction (UNKNOWN state).",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (lps:LogicalPipeSegment)\n"
                f"WHERE lps.flow_state = 'UNKNOWN'{pid_lps}\n"
                "RETURN 'no_flow_resolved' AS issue, lps.id AS target_id,\n"
                "       lps.phase4_hint AS hint\n"
                f"ORDER BY lps.id\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning="Listed pipe lines with no resolved flow direction (UNKNOWN state).",
        )

    # ── Junctions / T-pieces (degree >= 3) ───────────────────────────────
    if t & {"junction", "junctions", "tee", "t-junction", "crossing",
            "branch", "branches", "highdegree"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (n:Node)\n"
                    f"WHERE n.structural_type = 'SYMBOL'{pid_n}\n"
                    "  AND n.label <> 'background'\n"
                    "WITH n, size([(n)-[:PIPE]-(m:Node) | m]) AS deg\n"
                    "WHERE deg >= 3\n"
                    "RETURN count(n) AS junction_count"
                ),
                reasoning="Counted junction points with 3 or more pipe connections.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.structural_type = 'SYMBOL'{pid_n}\n"
                "  AND n.label <> 'background'\n"
                "WITH n, size([(n)-[:PIPE]-(m:Node) | m]) AS deg\n"
                "WHERE deg >= 3\n"
                "RETURN n.id AS node_id, n.label AS type, deg AS connections\n"
                f"ORDER BY deg DESC\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning=(
                "Listed junction points with 3 or more pipe connections, ordered by connection count."
            ),
        )

    # ── Endpoint count mismatches (pre-computed) ──────────────────────────
    if t & {"endpoint", "endpoints", "mismatch"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (a:Annotation)\n"
                    f"WHERE a.type = 'endpoint_count_mismatch'{pid_a}\n"
                    "RETURN count(a) AS total_mismatches"
                ),
                reasoning="Counted pipe runs with mismatched connection endpoint counts.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (a:Annotation)-[:ANNOTATES]->(ps:PipeSegment)\n"
                f"WHERE a.type = 'endpoint_count_mismatch'{pid_a}\n"
                "RETURN ps.id AS segment_id,\n"
                "       a.declared AS declared_endpoints,\n"
                "       a.found AS found_endpoints\n"
                f"ORDER BY ps.id\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning="Listed pipe runs with mismatched connection endpoint counts.",
        )

    # ── Duplicate / identical pipe geometry (via geometry_hash) ──────────
    # 'duplicate_symbol_candidate' does NOT exist in the live DB.
    # Use PipeSegment.geometry_hash grouping for genuine geometric duplicates.
    if t & {"duplicate", "duplicates"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (ps:PipeSegment)\n"
                    f"WHERE 1=1{pid_ps}\n"
                    "  AND ps.geometry_hash IS NOT NULL\n"
                    "WITH ps.geometry_hash AS hash, count(ps) AS cnt\n"
                    "WHERE cnt > 1\n"
                    "RETURN count(hash) AS duplicate_hash_groups,\n"
                    "       sum(cnt) AS total_segments_involved"
                ),
                reasoning="Counted groups of geometrically duplicate pipe runs.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (ps:PipeSegment)\n"
                f"WHERE 1=1{pid_ps}\n"
                "  AND ps.geometry_hash IS NOT NULL\n"
                "WITH ps.geometry_hash AS hash, collect(ps.id) AS segment_ids, count(ps) AS cnt\n"
                "WHERE cnt > 1\n"
                "RETURN hash AS geometry_hash, cnt AS count, segment_ids\n"
                f"ORDER BY cnt DESC\nLIMIT {_limit(slots, 30)}"
            ),
            reasoning="Listed groups of geometrically duplicate pipe runs, ordered by group size.",
        )

    # ── Validate / general quality — show all issue types ─────────────────
    if t & {"validate", "validation", "consistency", "quality", "issues",
            "problems", "errors", "check"}:
        return GeneratorResult(
            cypher=(
                "MATCH (a:Annotation)\n"
                f"WHERE a.intent = 'observation'{pid_a}\n"
                "RETURN a.type AS issue_type, count(a) AS total\n"
                "ORDER BY total DESC"
            ),
            reasoning="Counted all pre-analysed drawing quality issues, grouped by type.",
        )

    # ── Connectivity / are-all-connected check ────────────────────────────
    # Triggered by: "are all pipes connected?", "is everything connected?",
    # "verify connectivity", "check connectivity".
    # Queries the four annotation types that indicate physical connectivity gaps.
    # Zero rows = fully connected. Non-zero = connectivity issues by type.
    if t & {"connected", "connects", "connection", "connections", "connectivity"}:
        return GeneratorResult(
            cypher=(
                "MATCH (a:Annotation)-[:ANNOTATES]->(target)\n"
                f"WHERE a.type IN [\n"
                "  'orphan_node',\n"
                "  'pipe_segment_no_logical_mapping',\n"
                "  'dead_end_pipe_segment',\n"
                "  'pipe_segment_no_evidence_via_lps'\n"
                f"]{pid_a}\n"
                "RETURN a.type AS issue_type,\n"
                "       count(DISTINCT target) AS occurrences,\n"
                "       collect(DISTINCT target.id)[0..5] AS examples\n"
                "ORDER BY occurrences DESC"
            ),
            reasoning=(
                "Checked for connectivity issues: isolated symbols, unmapped pipe runs, dead ends, and unreachable pipe runs. Zero results means fully connected."
            ),
        )

    # ── Default: unresolved flow summary ──────────────────────────────────
    pid_lps_dc = _pid("lps", pid_id)
    if op == "count":
        return GeneratorResult(
            cypher=(
                "MATCH (lps:LogicalPipeSegment)\n"
                f"WHERE lps.flow_state = 'UNKNOWN'{pid_lps_dc}\n"
                "RETURN 'no_flow_resolved' AS issue_type, count(lps) AS total"
            ),
            reasoning="Counted pipe lines with no resolved flow direction.",
        )
    return GeneratorResult(
        cypher=(
            "MATCH (lps:LogicalPipeSegment)\n"
            f"WHERE lps.flow_state = 'UNKNOWN'{pid_lps_dc}\n"
            "RETURN 'no_flow_resolved' AS issue_type, count(lps) AS occurrences"
        ),
        reasoning="Summarised pipe lines with no resolved flow direction.",
    )


def _flow_direction(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    """
    Flow direction on pipe segments.

    CRITICAL:
    - Check lps.flow_state IN ['SEEDED','PROPAGATED'] before using lps.flow_direction
    - flow_state = 'UNKNOWN', 'BLOCKED', 'SEEDED_UNKNOWN' means flow_direction IS NULL
    - NEVER filter WHERE flow_direction = 'UNKNOWN' — 'UNKNOWN' is not a valid direction value
    - Evidence.direction is ALWAYS NULL — use Evidence.observed_direction
    - Low confidence flows: lps.flow_confidence < 0.5
      or via FLOW_EVIDENCE rel where Evidence.low_confidence = true
    """
    t      = set(kw)
    pid_lps = _pid("lps", pid_id)
    pid_n   = _pid("n", pid_id)
    seg_id = _safe_id(slots.get("tag"))
    seg_filter = f' AND lps.id = "{seg_id}"' if seg_id else ""

    # ── Upstream / downstream from a specific node ────────────────────────
    if t & {"upstream", "downstream"} and seg_id:
        is_downstream = "downstream" in t
        dir_label     = "downstream" if is_downstream else "upstream"
        # Flow exits seg_id when:
        #   FORWARD + lps starts with seg_id   (seg_id is natural-first, flow goes seg_id→other)
        #   REVERSE + lps ends   with seg_id   (seg_id is natural-last,  flow goes seg_id→first)
        if is_downstream:
            dir_filter = (
                f"  AND (\n"
                f"    (lps0.flow_direction = 'FORWARD' AND lps0.id STARTS WITH '{seg_id}__')\n"
                f"    OR\n"
                f"    (lps0.flow_direction = 'REVERSE' AND lps0.id ENDS WITH '__{seg_id}')\n"
                f"  )\n"
            )
        else:
            dir_filter = (
                f"  AND (\n"
                f"    (lps0.flow_direction = 'FORWARD' AND lps0.id ENDS WITH '__{seg_id}')\n"
                f"    OR\n"
                f"    (lps0.flow_direction = 'REVERSE' AND lps0.id STARTS WITH '{seg_id}__')\n"
                f"  )\n"
            )
        return GeneratorResult(
            cypher=(
                f'MATCH (start:Node {{id: "{seg_id}", pid_id: $pid_id}})-[:ENDPOINT_OF]->(lps0:LogicalPipeSegment)\n'
                f"WHERE lps0.flow_state IN ['SEEDED','PROPAGATED']\n"
                f"{dir_filter}"
                "MATCH (lps0)-[:ADJACENT_VIA_NODES*0..8]-(lps:LogicalPipeSegment)\n"
                "WHERE lps.flow_state IN ['SEEDED','PROPAGATED']\n"
                "MATCH (far:Node)-[:ENDPOINT_OF]->(lps)\n"
                "WHERE far.id <> start.id\n"
                "  AND far.structural_type = 'SYMBOL'\n"
                "  AND NOT far.label IN ['crossing','arrow']\n"
                "WITH far.id AS node_id, far.label AS type,\n"
                "     min(lps.id) AS via_segment,\n"
                "     min(lps.flow_state) AS flow_state,\n"
                "     min(lps.flow_confidence) AS confidence\n"
                "RETURN node_id, type, via_segment, flow_state, confidence\n"
                f"ORDER BY type, node_id\n"
                f"LIMIT {_limit(slots, 50)}"
            ),
            reasoning=(
                f"Traced all {dir_label} flow paths from '{seg_id}', "
                f"following connected pipe segments to list equipment along the full flow path."
            ),
        )

    if t & {"low", "uncertain", "ambiguous", "confidence", "unclear"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (lps:LogicalPipeSegment)\n"
                    f"WHERE lps.flow_state IN ['SEEDED','PROPAGATED']{pid_lps}\n"
                    "  AND lps.flow_confidence < 0.5\n"
                    "RETURN count(lps) AS low_confidence_segments"
                ),
                reasoning="Counted pipe lines with confirmed but low-confidence flow direction.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (arr:Arrow)-[fe:FLOW_EVIDENCE]->(lps:LogicalPipeSegment)\n"
                f"WHERE lps.flow_state IN ['SEEDED','PROPAGATED']{pid_lps}\n"
                f"  AND lps.flow_confidence < 0.5{seg_filter}\n"
                "OPTIONAL MATCH (ev:Evidence)-[:ABOUT]->(lps)\n"
                "RETURN lps.id AS segment_id,\n"
                "       lps.flow_direction AS direction,\n"
                "       lps.flow_confidence AS confidence,\n"
                "       ev.observed_direction AS evidence_direction,\n"
                "       fe.low_confidence AS low_confidence_flag\n"
                f"ORDER BY lps.flow_confidence ASC\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning=(
                "Listed pipe lines with low-confidence flow direction, using arrow evidence and observed direction; ordered by confidence ascending."
            ),
        )

    if t & {"unknown", "unannotated", "missing", "none"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (lps:LogicalPipeSegment)\n"
                    f"WHERE lps.flow_state IN ['UNKNOWN','SEEDED_UNKNOWN','BLOCKED']{pid_lps}\n"
                    "RETURN count(lps) AS segments_without_flow"
                ),
                reasoning="Counted pipe lines with no resolved or ambiguous flow direction.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (lps:LogicalPipeSegment)\n"
                f"WHERE lps.flow_state IN ['UNKNOWN','SEEDED_UNKNOWN','BLOCKED']{pid_lps}\n"
                "RETURN lps.id AS segment_id,\n"
                "       lps.flow_state AS flow_state,\n"
                "       lps.phase4_hint AS reason,\n"
                "       lps.length AS length\n"
                f"ORDER BY lps.flow_state, lps.id\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning="Listed pipe lines with unresolved or ambiguous flow direction, with diagnostic reasons.",
        )

    if op == "count":
        return GeneratorResult(
            cypher=(
                "MATCH (lps:LogicalPipeSegment)\n"
                f"WHERE lps.flow_state IN ['SEEDED','PROPAGATED']{pid_lps}\n"
                "RETURN lps.flow_direction AS direction, count(lps) AS total\n"
                "ORDER BY total DESC"
            ),
            reasoning=(
                "Counted pipe lines with confirmed flow direction, grouped by direction (forward/reverse)."
            ),
        )

    if seg_id:
        return GeneratorResult(
            cypher=(
                f'MATCH (lps:LogicalPipeSegment {{id: "{seg_id}"}})\n'
                "OPTIONAL MATCH (arr:Arrow)-[fe:FLOW_EVIDENCE]->(lps)\n"
                "OPTIONAL MATCH (ev:Evidence)-[:ABOUT]->(lps)\n"
                "RETURN lps.id AS segment_id,\n"
                "       lps.flow_state AS flow_state,\n"
                "       lps.flow_direction AS direction,\n"
                "       lps.flow_confidence AS confidence,\n"
                "       lps.flow_source AS how_determined,\n"
                "       lps.phase4_hint AS issue,\n"
                "       ev.observed_direction AS evidence_direction,\n"
                "       fe.low_confidence AS low_confidence\n"
                f"LIMIT 1"
            ),
            reasoning=f"Looked up flow direction for pipe line '{seg_id}' including diagnostic issue hint.",
        )

    return GeneratorResult(
        cypher=(
            "MATCH (lps:LogicalPipeSegment)\n"
            f"WHERE lps.flow_state IN ['SEEDED','PROPAGATED']{pid_lps}{seg_filter}\n"
            "OPTIONAL MATCH (arr:Arrow)-[fe:FLOW_EVIDENCE]->(lps)\n"
            "RETURN lps.id AS segment_id,\n"
            "       lps.flow_direction AS direction,\n"
            "       lps.flow_confidence AS confidence,\n"
            "       fe.low_confidence AS low_confidence_flag\n"
            f"ORDER BY lps.flow_confidence ASC\nLIMIT {_limit(slots, 50)}"
        ),
        reasoning=(
            "Listed pipe lines with their flow direction and arrow evidence confidence; ordered by confidence ascending."
        ),
    )


def _isolation_reachability(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    t       = set(kw)
    pid_ps  = _pid("ps", pid_id)
    pid_a   = _pid("a", pid_id)
    node_id = _safe_id(slots.get("tag"))

    if t & {"component", "components", "island", "islands"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (ps:PipeSegment)\n"
                    "RETURN count(DISTINCT ps.component_id) AS total_components"
                ),
                reasoning="Counted isolated pipe network sections on the drawing.",
            )
        return GeneratorResult(
            cypher=(
                f"MATCH (ps:PipeSegment)\n"
                f"WHERE 1=1{pid_ps}\n"
                "RETURN ps.component_id AS component,\n"
                "       count(ps) AS segments_in_component,\n"
                "       sum(ps.node_count) AS total_nodes\n"
                "ORDER BY segments_in_component DESC\n"
                f"LIMIT {_limit(slots, 30)}"
            ),
            reasoning="Listed isolated pipe network sections, ordered by size.",
        )

    if node_id:
        return GeneratorResult(
            cypher=(
                f'MATCH (start:Node {{id: "{node_id}"}})\n'
                "MATCH (start)-[:PIPE*1..20]-(reached:Node)\n"
                "WHERE reached.label <> 'background'\n"
                "RETURN count(DISTINCT reached) AS reachable_nodes,\n"
                "       collect(DISTINCT reached.label)[0..10] AS types_reached"
            ),
            reasoning=(
                f"Counted all symbols reachable from '{node_id}' by following pipe connections."
            ),
        )

    # ── Small / tiny isolated components (fewer than N segments) ─────────
    # Triggered by words like "small", "tiny", "few", "single", "only one".
    if t & {"small", "tiny", "few", "single", "lone", "only"}:
        threshold = 5  # default: components with < 5 PipeSegments
        for n_val in slots.get("numbers", []):
            try:
                threshold = int(n_val)
                break
            except (ValueError, TypeError):
                pass
        if op == "count":
            return GeneratorResult(
                cypher=(
                    f"MATCH (ps:PipeSegment)\n"
                    f"WHERE 1=1{pid_ps}\n"
                    "WITH ps.component_id AS component, count(ps) AS seg_count\n"
                    f"WHERE seg_count < {threshold}\n"
                    "RETURN count(component) AS small_component_count"
                ),
                reasoning=(
                    f"Counted small isolated pipe sections with fewer than {threshold} pipe runs."
                ),
            )
        return GeneratorResult(
            cypher=(
                f"MATCH (ps:PipeSegment)\n"
                f"WHERE 1=1{pid_ps}\n"
                "WITH ps.component_id AS component, count(ps) AS seg_count,\n"
                "     sum(ps.node_count) AS total_nodes\n"
                f"WHERE seg_count < {threshold}\n"
                "RETURN component, seg_count, total_nodes\n"
                f"ORDER BY seg_count\nLIMIT {_limit(slots, 30)}"
            ),
            reasoning=(
                f"Listed small isolated pipe sections with fewer than {threshold} pipe runs, ordered by size."
            ),
        )

    if op == "count":
        return GeneratorResult(
            cypher=(
                "MATCH (a:Annotation)-[:ANNOTATES]->(n:Node)\n"
                f"WHERE a.type = 'orphan_node'{pid_a}\n"
                "  AND NOT n.label IN ['arrow', 'crossing', 'background']\n"
                "RETURN count(a) AS total_isolated_nodes"
            ),
            reasoning="Counted isolated symbols with no pipe connections.",
        )
    return GeneratorResult(
        cypher=(
            "MATCH (a:Annotation)-[:ANNOTATES]->(n:Node)\n"
            f"WHERE a.type = 'orphan_node'{pid_a}\n"
            "  AND NOT n.label IN ['arrow', 'crossing', 'background']\n"
            "RETURN n.id AS node_id, n.label AS type,\n"
            "       n.structural_type AS structural_type\n"
            f"ORDER BY n.label\nLIMIT {_limit(slots, 50)}"
        ),
        reasoning="Listed isolated symbols with no pipe connections.",
    )



def _annotation_requests(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    """
    AnnotationRequest nodes — human/system-raised review flags on specific Nodes.
    Pattern: (PID)-[:HAS_ANNOTATION]->(AnnotationRequest)-[:CONCERNS]->(Node)
    """
    t = set(kw)
    pid_ar = _pid("ar", pid_id)

    # Note: only ar.status = 'OPEN' is confirmed to exist in the live DB.
    # PENDING and RESOLVED do not appear — filter on those will return 0.
    if op == "count":
        return GeneratorResult(
            cypher=(
                "MATCH (p:PID)-[:HAS_ANNOTATION]->(ar:AnnotationRequest)\n"
                f"WHERE 1=1{pid_ar}\n"
                "RETURN count(ar) AS total_requests"
            ),
            reasoning="Counted open drawing quality requests on the P&ID.",
        )

    return GeneratorResult(
        cypher=(
            "MATCH (p:PID)-[:HAS_ANNOTATION]->(ar:AnnotationRequest)\n"
            "OPTIONAL MATCH (ar)-[:CONCERNS]->(n:Node)\n"
            "RETURN ar.request_id AS request_id,\n"
            "       ar.anomaly_type AS anomaly_type,\n"
            "       ar.status AS status,\n"
            "       ar.detail AS detail,\n"
            "       n.id AS node_id,\n"
            "       n.label AS node_type\n"
            f"ORDER BY ar.status\nLIMIT {_limit(slots, 50)}"
        ),
        reasoning="Listed open drawing quality requests with the symbol each one flags.",
    )


def _segment_junction_topology(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    """
    Junction and adjacency topology between PipeSegments.
    JOINS_AT: PipeSegment → PipeSegment with kind and trace_nodes.
    trace_nodes[1] = junction symbol; indices 0 and 2 = connectors.
    ADJACENT_VIA_NODES: both PipeSegment↔PipeSegment and LPS↔LPS.
    """
    t       = set(kw)
    pid_lps = _pid("lps1", pid_id)
    pid_ps  = _pid("ps1", pid_id)
    seg_id  = slots.get("tag")

    if t & {"adjacent", "adjacency"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (ps1:PipeSegment)-[adj:ADJACENT_VIA_NODES]->(ps2:PipeSegment)\n"
                    "RETURN count(adj) AS total_adjacent_pairs"
                ),
                reasoning="Counted adjacent pipe run pairs on the drawing.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (ps1:PipeSegment)-[adj:ADJACENT_VIA_NODES]->(ps2:PipeSegment)\n"
                "RETURN ps1.id AS segment_a, ps2.id AS segment_b,\n"
                "       adj.via_count AS shared_nodes\n"
                f"ORDER BY adj.via_count DESC\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning=(
                "Listed adjacent pipe run pairs, ordered by number of shared connection points."
            ),
        )

    # Default: JOINS_AT junction list
    seg_filter = f'\nAND (ps1.id = "{seg_id}" OR ps2.id = "{seg_id}")' if seg_id else ""
    if op == "count":
        return GeneratorResult(
            cypher=(
                "MATCH (ps1:PipeSegment)-[j:JOINS_AT]->(ps2:PipeSegment)\n"
                f"WHERE ps1.pid_id IS NOT NULL{seg_filter}\n"
                "RETURN count(j) AS total_junctions"
            ),
            reasoning="Counted junction points between pipe runs on the drawing.",
        )
    return GeneratorResult(
        cypher=(
            "MATCH (ps1:PipeSegment)-[j:JOINS_AT]->(ps2:PipeSegment)\n"
            f"WHERE 1=1{pid_ps}{seg_filter}\n"
            "RETURN ps1.id AS segment_a,\n"
            "       j.kind AS junction_kind,\n"
            "       j.trace_nodes[1] AS junction_symbol,\n"
            "       ps2.id AS segment_b\n"
            f"ORDER BY ps1.id\nLIMIT {_limit(slots, 50)}"
        ),
        reasoning="Listed junction points between pipe runs with the junction symbol type.",
    )



def _engineering_correctness(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    """
    Topology-based engineering correctness checks.

    No tag names required — uses label, connectivity, and flow direction only.
    Checks are heuristic; results require engineer review.

    Sub-intents:
        instrument coverage  — tanks with no instrument within N hops
        valve isolation      — tanks with no valve on any connecting path
        bypass existence     — degree-3 valves with no parallel path
        boundary integrity   — inlet/outlet nodes with unexpected degree
        default              — full correctness summary across all checks
    """
    t      = set(kw)
    pid_t  = _pid("t", pid_id)
    pid_v  = _pid("v", pid_id)
    pid_io = _pid("io", pid_id)
    pid_a  = _pid("a", pid_id)

    # ── Pump + check valve: "which pumps are missing a check valve?" ──────
    # Must fire BEFORE the isolation valve branch because "valve" appears in
    # both queries.  When "pump/pumps" AND ("check" OR "missing") are present
    # together with "valve", the user wants violation data, not heuristic topology.
    # Returns columns in the engineering_rule_violation layout so the server's
    # highlight Path C fires correctly (issue_type, severity, explanation).
    _is_pump_check = bool(
        t & {"pump", "pumps"}
        and t & {"check"}
        and t & {"valve", "valves"}
    )
    _is_pump_missing_valve = bool(
        t & {"pump", "pumps"}
        and t & {"missing", "no", "without", "lack"}
        and t & {"valve", "valves", "checkvalve", "check-valve"}
    )
    if _is_pump_check or _is_pump_missing_valve:
        return GeneratorResult(
            cypher=(
                "MATCH (a:Annotation)\n"
                f"WHERE a.type = 'engineering_rule_violation'{pid_a}\n"
                "  AND a.pattern_type = 'missing_check_valve'\n"
                "OPTIONAL MATCH (a)-[:ANNOTATES]->(n:Node)\n"
                "RETURN coalesce(n.id, a.target_id)  AS node_id,\n"
                "       coalesce(n.label, 'tank')     AS label,\n"
                "       a.pattern_type                AS issue_type,\n"
                "       a.severity                    AS severity,\n"
                "       a.explanation                 AS explanation,\n"
                "       a.target_id                   AS affected_equipment\n"
                f"ORDER BY a.severity\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning=(
                "Queried engineering rule violations of type 'missing_check_valve' "
                "to find pumps without downstream check valve protection. "
                "Zero rows means all pumps have check valve coverage; "
                "non-zero rows are CRITICAL violations requiring immediate review."
            ),
        )

    # ── Reverse flow protection: check valve coverage ──────────────────
    # "is there reverse flow protection?" / "reverse flow protection"
    if t & {"reverse"} and t & {"protection", "flow"}:
        return GeneratorResult(
            cypher=(
                "MATCH (a:Annotation)\n"
                f"WHERE a.type = 'engineering_rule_violation'{pid_a}\n"
                "  AND a.pattern_type = 'missing_check_valve'\n"
                "RETURN a.target_id AS equipment_without_protection,\n"
                "       a.severity AS severity,\n"
                "       a.explanation AS explanation\n"
                f"ORDER BY a.severity\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning=(
                "Checked reverse flow protection: listed equipment missing a check valve. "
                "Zero results means all equipment has adequate check valve protection."
            ),
        )

    # ── Suction strainer coverage ─────────────────────────────────────────
    # "missing suction strainer" / "suction strainer check"
    if t & {"strainer", "suction"}:
        return GeneratorResult(
            cypher=(
                "MATCH (a:Annotation)\n"
                f"WHERE a.type = 'engineering_rule_violation'{pid_a}\n"
                "  AND a.pattern_type = 'missing_suction_strainer'\n"
                "RETURN a.target_id AS equipment_without_strainer,\n"
                "       a.severity AS severity,\n"
                "       a.explanation AS explanation\n"
                f"ORDER BY a.severity\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning=(
                "Checked suction strainer coverage: listed equipment missing a suction "
                "strainer. Zero results means all pump suction lines are protected."
            ),
        )

    # ── Pre-computed rule violations (Phase 3.5 Annotations) ────────────
    # "Are there any engineering rule violations?" / "show violations" / "rule violations"
    if t & {"violation", "violations", "rule", "rules"}:
        # Sub-type filtering: "missing check valve violations" / "isolation valve violations"
        pattern_filter = ""
        pattern_desc   = ""
        if t & {"check"}:
            pattern_filter = "\n  AND a.pattern_type = 'missing_check_valve'"
            pattern_desc   = " (missing check valve)"
        elif t & {"isolation", "isolat"}:
            pattern_filter = "\n  AND a.pattern_type = 'missing_isolation_valve'"
            pattern_desc   = " (missing isolation valve)"
        elif t & {"strainer", "suction"}:
            pattern_filter = "\n  AND a.pattern_type = 'missing_suction_strainer'"
            pattern_desc   = " (missing suction strainer)"

        # Severity filtering: "critical violations" / "high severity violations"
        severity_filter = ""
        severity_desc   = ""
        if t & {"critical"}:
            severity_filter = "\n  AND a.severity = 'CRITICAL'"
            severity_desc   = ", severity=CRITICAL"
        elif t & {"high"}:
            severity_filter = "\n  AND a.severity = 'HIGH'"
            severity_desc   = ", severity=HIGH"
        elif t & {"medium"}:
            severity_filter = "\n  AND a.severity = 'MEDIUM'"
            severity_desc   = ", severity=MEDIUM"

        return GeneratorResult(
            cypher=(
                "MATCH (a:Annotation)\n"
                f"WHERE a.type = 'engineering_rule_violation'{pid_a}"
                f"{pattern_filter}{severity_filter}\n"
                "RETURN a.id AS violation_id,\n"
                "       a.pattern_type AS rule_name,\n"
                "       a.severity AS severity,\n"
                "       a.explanation AS explanation,\n"
                "       a.target_id AS affected_equipment,\n"
                "       a.required_equipment AS required_equipment,\n"
                "       a.hitl_status AS review_status\n"
                f"ORDER BY CASE a.severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' "
                f"THEN 2 WHEN 'MEDIUM' THEN 3 ELSE 4 END, a.id\n"
                f"LIMIT {_limit(slots, 50)}"
            ),
            reasoning=(
                f"Queried pre-computed engineering rule violations{pattern_desc}{severity_desc} "
                "from Phase 3.5 Annotation nodes. "
                "Sorted by severity: CRITICAL > HIGH > MEDIUM."
            ),
        )

    # ── Instrument coverage: tanks with no instrument nearby ─────────────
    if t & {"instrument", "instruments", "instrumented", "instrumentation",
            "monitored", "sensor", "measurement"}:
        return GeneratorResult(
            cypher=(
                "MATCH (t:Node {label:'tank'})\n"
                f"WHERE 1=1{pid_t}\n"
                "  AND NOT EXISTS {\n"
                "    MATCH (t)-[:PIPE*1..5]-(inst:Node {label:'instrumentation'})\n"
                "  }\n"
                "RETURN t.id AS tank_id,\n"
                "       coalesce(t.functional_label, t.label) AS equipment_role,\n"
                "       round((t.xmax - t.xmin), 1) AS width,\n"
                "       round((t.ymax - t.ymin), 1) AS height\n"
                f"ORDER BY t.id\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning=(
                "Checked all tank symbols for instrumentation: listed tanks that have "
                "no instrument symbol within 5 pipe hops. equipment_role='pump' means "
                "the node is a condensate pump unit, not a storage vessel."
            ),
        )

    # ── Valve isolation: tanks that cannot reach any valve ───────────────
    if t & {"isolat", "isolation", "isolatable", "isolable",
            "valve", "valves", "shutoff", "shut"}:
        return GeneratorResult(
            cypher=(
                "MATCH (t:Node {label:'tank'})\n"
                f"WHERE 1=1{pid_t}\n"
                "  AND NOT EXISTS {\n"
                "    MATCH (t)-[:PIPE*1..8]-(v:Node {label:'valve'})\n"
                "  }\n"
                "RETURN t.id AS tank_id,\n"
                "       coalesce(t.functional_label, t.label) AS equipment_role,\n"
                "       round((t.xmax - t.xmin), 1) AS width,\n"
                "       round((t.ymax - t.ymin), 1) AS height\n"
                f"ORDER BY t.id\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning=(
                "Checked all tank symbols for reachable isolation valves: listed tanks "
                "that cannot reach any valve within 8 pipe hops. "
                "equipment_role='pump' means condensate pump unit, not a storage vessel."
            ),
        )

    # ── Bypass existence: degree-3 valves (potential bypass junctions) ───
    if t & {"bypass", "bypassed", "parallel", "alternative", "redundant",
            "degree-3", "branch"}:
        return GeneratorResult(
            cypher=(
                "MATCH (v:Node {label:'valve'})\n"
                f"WHERE 1=1{pid_v}\n"
                "WITH v, size([(v)-[:PIPE]-() | 1]) AS deg\n"
                "WHERE deg >= 3\n"
                "RETURN v.id AS branching_valve,\n"
                "       deg AS degree,\n"
                "       v.xmin AS x, v.ymin AS y\n"
                f"ORDER BY deg DESC\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning=(
                "Listed valves with 3 or more pipe connections (potential bypass junction). "
                "These are candidates for bypass verification — confirm each has an "
                "alternative flow path that does not pass through the valve."
            ),
        )

    # ── Boundary integrity: inlet/outlet degree check ────────────────────
    if t & {"boundary", "inlet", "outlet", "interface", "interfaces", "external"}:
        return GeneratorResult(
            cypher=(
                "MATCH (io:Node {label:'inlet/outlet'})\n"
                f"WHERE 1=1{pid_io}\n"
                "WITH io, size([(io)-[:PIPE]-() | 1]) AS deg\n"
                "RETURN io.id AS interface_id,\n"
                "       deg AS degree,\n"
                "       CASE WHEN deg = 1 THEN 'OK' ELSE 'UNEXPECTED DEGREE' END AS status\n"
                f"ORDER BY deg DESC\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning=(
                "Checked all boundary interface nodes (inlet/outlet) for expected "
                "degree of 1. Any node with degree <> 1 is a topology anomaly."
            ),
        )

    # ── Default: full correctness summary ────────────────────────────────
    return GeneratorResult(
        cypher=(
            "MATCH (t:Node {label:'tank'})\n"
            f"WHERE 1=1{pid_t}\n"
            "WITH count(t) AS total_tanks,\n"
            "     sum(CASE WHEN t.functional_label = 'pump' THEN 1 ELSE 0 END) AS pump_count,\n"
            "     sum(CASE WHEN EXISTS {\n"
            "         MATCH (t)-[:PIPE*1..5]-(i:Node {label:'instrumentation'})\n"
            "     } THEN 0 ELSE 1 END) AS tanks_without_instrument\n"
            "MATCH (v2:Node {label:'valve'})\n"
            f"WHERE 1=1{pid_v}\n"
            "WITH total_tanks, pump_count, tanks_without_instrument,\n"
            "     sum(CASE WHEN size([(v2)-[:PIPE]-() | 1]) >= 3 THEN 1 ELSE 0 END)\n"
            "       AS branching_valves\n"
            "MATCH (io:Node {label:'inlet/outlet'})\n"
            f"WHERE 1=1{pid_io}\n"
            "WITH total_tanks, pump_count, tanks_without_instrument, branching_valves,\n"
            "     sum(CASE WHEN size([(io)-[:PIPE]-() | 1]) <> 1 THEN 1 ELSE 0 END)\n"
            "       AS boundary_anomalies\n"
            "RETURN total_tanks,\n"
            "       pump_count,\n"
            "       (total_tanks - pump_count) AS vessel_count,\n"
            "       tanks_without_instrument,\n"
            "       branching_valves,\n"
            "       boundary_anomalies"
        ),
        reasoning=(
            "Engineering correctness summary: (1) tanks with no nearby instrument "
            "(includes both vessels and pumps — use pump_count/vessel_count to distinguish), "
            "(2) branching valves (degree >= 3, potential bypass points), "
            "(3) boundary interface degree anomalies. "
            "No tag names used — topology only."
        ),
    )


def _flow_coverage(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    """
    Flow direction analysis coverage — how many pipe lines have a resolved
    flow direction vs how many remain unresolved, and why.

    This is an analysis completeness metric, NOT a drawing defect check.
    Arrow placement is sparse on real P&IDs; unresolved pipe lines are normal.

    flow_state values:
        SEEDED         — direction confirmed directly from a drawing arrow
        PROPAGATED     — direction inferred by tracing from a seeded neighbour
        SEEDED_UNKNOWN — evidence present but conflicting arrows; direction unclear
        BLOCKED        — structurally isolated segment; direction not applicable
        UNKNOWN        — could not be determined; no nearby arrow evidence
    """
    t = set(kw)
    pid_lps = _pid("lps", pid_id)
    pid_a   = _pid("a", pid_id)

    # ── Gap detail: which pipe lines have no flow direction ───────────────
    if t & {"missing", "gap", "gaps", "unresolved", "unknown", "no"}:
        if op == "count":
            return GeneratorResult(
                cypher=(
                    "MATCH (lps:LogicalPipeSegment)\n"
                    f"WHERE lps.flow_state IN ['UNKNOWN','SEEDED_UNKNOWN','BLOCKED']{pid_lps}\n"
                    "RETURN count(lps) AS unresolved_pipe_lines"
                ),
                reasoning="Counted pipe lines with no resolved, ambiguous, or blocked flow direction.",
            )
        return GeneratorResult(
            cypher=(
                "MATCH (lps:LogicalPipeSegment)\n"
                f"WHERE lps.flow_state IN ['UNKNOWN','SEEDED_UNKNOWN','BLOCKED']{pid_lps}\n"
                "RETURN lps.id AS pipe_line,\n"
                "       lps.flow_state AS flow_state,\n"
                "       lps.phase4_hint AS reason,\n"
                "       lps.length AS length\n"
                f"ORDER BY lps.flow_state, lps.id\nLIMIT {_limit(slots, 50)}"
            ),
            reasoning="Listed pipe lines with unresolved, ambiguous, or blocked flow direction, with diagnostic reasons.",
        )

    # ── Default: full coverage summary ───────────────────────────────────
    return GeneratorResult(
        cypher=(
            "MATCH (lps:LogicalPipeSegment)\n"
            f"WHERE 1=1{pid_lps}\n"
            "WITH count(lps) AS total,\n"
            "     sum(CASE WHEN lps.flow_state IN ['SEEDED','PROPAGATED'] THEN 1 ELSE 0 END) AS resolved,\n"
            "     sum(CASE WHEN lps.flow_state = 'SEEDED_UNKNOWN' THEN 1 ELSE 0 END) AS ambiguous,\n"
            "     sum(CASE WHEN lps.flow_state = 'BLOCKED' THEN 1 ELSE 0 END) AS blocked,\n"
            "     sum(CASE WHEN lps.flow_state = 'UNKNOWN' THEN 1 ELSE 0 END) AS unresolved\n"
            "RETURN total AS total_pipe_lines,\n"
            "       resolved AS flow_direction_resolved,\n"
            "       ambiguous AS conflicting_arrows,\n"
            "       blocked AS structurally_isolated,\n"
            "       unresolved AS flow_direction_unresolved,\n"
            "       round(100.0 * resolved / total, 1) AS coverage_percent"
        ),
        reasoning=(
            "Summarised flow direction coverage: total pipe lines, how many have "
            "a resolved direction (SEEDED or PROPAGATED), how many have conflicting arrows "
            "(SEEDED_UNKNOWN), how many are structurally isolated (BLOCKED), how many "
            "remain unresolved (UNKNOWN), and overall coverage percentage."
        ),
    )


def _generic(op: str, slots: Dict, kw: List[str], pid_id: str = "UNKNOWN") -> GeneratorResult:
    pid_n = _pid("n", pid_id)
    if op == "count":
        return GeneratorResult(
            cypher=(
                "MATCH (n:Node)\n"
                f"WHERE n.structural_type = 'SYMBOL'{pid_n}\n"
                "  AND n.label <> 'background'\n"
                "RETURN n.label AS type, count(n) AS total\n"
                "ORDER BY total DESC"
            ),
            reasoning="Counted all equipment symbols on the drawing, grouped by type.",
        )
    return GeneratorResult(
        cypher=(
            "MATCH (n:Node)\n"
            "WHERE n.structural_type = 'SYMBOL'\n"
            "  AND n.label <> 'background'\n"
            "RETURN n.id AS node_id, n.label AS type\n"
            f"ORDER BY n.label\nLIMIT {_limit(slots, 50)}"
        ),
        reasoning="Listed all equipment symbols on the drawing.",
    )


# ---------------------------------------------------------------------------
# Generator dispatch table
# ---------------------------------------------------------------------------

_GENERATORS: Dict[str, Any] = {
    "engineering_inventory":    _engineering_inventory,
    "valve_placement":          _valve_placement,
    "instrument_attachment":    _instrument_attachment,
    "line_attributes":          _line_attributes,
    "connectivity_topology":    _connectivity_topology,
    "external_interfaces":      _external_interfaces,
    "redundancy_patterns":      _redundancy_patterns,
    "drawing_consistency":      _drawing_consistency,
    "flow_direction":           _flow_direction,
    "engineering_correctness":  _engineering_correctness,
    "flow_coverage":            _flow_coverage,
    "isolation_reachability":   _isolation_reachability,
    "annotation_requests":      _annotation_requests,
    "segment_junction_topology": _segment_junction_topology,
    "cross_domain":             _generic,   # SchemaGenerator fallback; primary path is GroundedGenerator
    "custom_query":             _generic,   # catch-all → generic SYMBOL list
}


def _pid(alias: str, pid_id: str) -> str:
    """
    Returns an AND clause scoping a query to one PID when pid_id is known.
    Returns an empty string when pid_id is 'UNKNOWN' so single-PID deployments
    continue to work without any WHERE change.

    Usage inside a Cypher f-string:
        f"WHERE n.label = 'valve'{_pid('n', pid_id)}\\n"
    """
    if not pid_id or pid_id == "UNKNOWN":
        return ""
    return f' AND {alias}.pid_id = "{pid_id}"'


def _limit(slots: Dict, default: int = 50) -> int:
    numbers = slots.get("numbers", [])
    if numbers:
        try:
            return max(1, int(numbers[0]))
        except (ValueError, TypeError):
            pass
    return default


def _safe_id(val: Optional[str]) -> Optional[str]:
    """
    Validate a user-supplied node/entity ID before inlining into a Cypher
    f-string template.  Returns None (and logs a warning) if the value
    contains characters that could be used for Cypher injection.

    Allowed characters match _SAFE_SLOT_RE: alphanumeric, _ / . - : space.
    Quotes, parentheses, angle-brackets, etc. are rejected.
    """
    if val is None:
        return None
    v = str(val).strip()
    if not v:
        return None
    if not _SAFE_SLOT_RE.match(v):
        bad = {c for c in v if not re.match(r'[A-Za-z0-9_/.\-: ]', c)}
        logger.warning(
            "[HybridOptimizer] Rejected unsafe node id from slots: %r (bad chars: %r)",
            v, bad,
        )
        return None
    return v


# ---------------------------------------------------------------------------
# Hybrid Optimizer
# ---------------------------------------------------------------------------

class HybridOptimizer:
    """
    Orchestrates four-tier Cypher resolution:

        Tier 1:   TemplateMatcher     → validated hardcoded Cypher (zero latency)
        Tier 2:   Registry file       → pre-built Phase 5 .cypher (fixed queries)
        Tier 3:   GroundedGenerator   → LLM-powered Cypher (customisable queries;
                                        only for questions with entity-specific
                                        filters or when no registry file matches)
        Tier 4:   SchemaGenerator     → deterministic generator fallback (when
                                        LLM is unavailable or fails)

    Fixed queries (Phase 5) are preferred for deterministic, pre-validated
    answers. The LLM is reserved for questions requiring custom filtering
    (entity tags, specific node IDs, numeric thresholds, compound conditions).

    OptimizerResult.reasoning is populated at every tier so TraceAdapter
    always receives a human-readable description of what was queried.
    """

    def __init__(
        self,
        registry:           QueryRegistry,
        template_matcher:   TemplateMatcher,
        schema_generator:   SchemaGenerator,
        grounded_generator: Optional[Any] = None,  # GroundedGenerator | None
    ) -> None:
        self._registry           = registry
        self._template_matcher   = template_matcher
        self._schema_generator   = schema_generator
        self._grounded_generator = grounded_generator

    def optimize(
        self,
        query_entry: QueryEntry,
        intent: Dict[str, Any],
    ) -> OptimizerResult:
        slots       = intent.get("slots", {})
        intent_type = intent.get("intent_type", "unknown")
        operation   = query_entry.get("operation", "list")
        pid_id      = intent.get("pid_id", "UNKNOWN")

        # ── Tier 1: hardcoded template (zero latency) ──
        cypher = self._template_matcher.match(query_entry, slots)
        if cypher is not None:
            return OptimizerResult(
                cypher      = cypher,
                strategy    = "template",
                query_entry = query_entry,
                reasoning   = "Answered using a pre-built query pattern for this question type.",
                metadata    = {"template_id": query_entry["id"]},
            )

        # ── Tier 2: Phase 5 registry file (fixed queries) ──
        # Use pre-validated .cypher from engine/phase5_cypher/ when:
        #   - The QueryEntry has a cypher_file path
        #   - pid_id is known (Phase 5 files use $pid_id parameter)
        #   - The question does NOT need LLM customisation (no equipment
        #     tags that require entity-specific Cypher)
        cypher_file = query_entry.get("cypher_file", "")
        # Escalate to LLM when the question references specific equipment
        # tags (FV-001) or node IDs (tank67, valve12) that need dynamic Cypher.
        _has_tag       = bool(slots.get("tag"))
        _has_node_ref  = bool(re.search(
            r'\b(?:tank|valve|connector|arrow|instrument)\d+\b',
            intent.get("raw", ""),
            re.IGNORECASE,
        ))
        _needs_llm_customisation = _has_tag or _has_node_ref

        if cypher_file and pid_id != "UNKNOWN" and not _needs_llm_customisation:
            try:
                cypher = self._registry.resolve_cypher(query_entry)
                return OptimizerResult(
                    cypher      = cypher,
                    strategy    = "registry_file",
                    query_entry = query_entry,
                    reasoning   = (
                        f"Answered using pre-built Phase 5 query: "
                        f"{query_entry.get('title', query_entry['id'])}"
                    ),
                    metadata    = {"cypher_file": cypher_file},
                )
            except (FileNotFoundError, RuntimeError) as exc:
                logger.warning(
                    "[HybridOptimizer] Phase 5 file '%s' failed: %s — "
                    "falling through to LLM",
                    cypher_file,
                    exc,
                )

        # ── Tier 3 bypass: upstream/downstream topology → SchemaGenerator directly ──
        # The LLM tends to generate undirected PIPE*1..N traversal which hits only
        # connector nodes and returns zero results.  The SchemaGenerator has a
        # verified ENDPOINT_OF → LogicalPipeSegment query that is provably correct.
        # Skip the LLM entirely for this case.
        _kw_set = set(intent.get("keywords", []))
        if (intent_type == "connectivity_topology"
                and _kw_set & {"upstream", "downstream"}
                and slots.get("tag")):
            try:
                schema_result: GeneratorResult = self._schema_generator.generate(query_entry, intent)
                return OptimizerResult(
                    cypher      = schema_result.cypher,
                    strategy    = "schema_generated",
                    query_entry = query_entry,
                    reasoning   = schema_result.reasoning,
                    metadata    = {"intent_type": intent_type, "slots": slots},
                )
            except NotImplementedError:
                pass  # fall through to LLM/SchemaGenerator below

        # ── Tier 3: LLM-grounded generator (customisable queries) ──
        # Runs for questions that need entity-specific filtering, complex
        # conditions, or when no fixed Phase 5 query was matched.
        if self._grounded_generator is not None:
            try:
                result: GeneratorResult = self._grounded_generator.generate(query_entry, intent)
                return OptimizerResult(
                    cypher      = result.cypher,
                    strategy    = "llm_grounded",
                    query_entry = query_entry,
                    reasoning   = result.reasoning,
                    metadata    = {
                        "intent_type": intent_type,
                        "slots":       slots,
                    },
                )
            except NotImplementedError:
                logger.warning(
                    "[HybridOptimizer] GroundedGenerator failed for "
                    "'%s' (query_id='%s') — falling back to SchemaGenerator",
                    intent_type,
                    query_entry.get("id", "?"),
                )

        # ── Tier 4: schema generator (deterministic fallback) ──
        try:
            schema_result: GeneratorResult = self._schema_generator.generate(query_entry, intent)
            return OptimizerResult(
                cypher      = schema_result.cypher,
                strategy    = "schema_generated",
                query_entry = query_entry,
                reasoning   = schema_result.reasoning,
                metadata    = {
                    "intent_type": intent_type,
                    "slots":       slots,
                },
            )
        except NotImplementedError as _tier4_exc:
            logger.error(
                "[HybridOptimizer] All tiers exhausted for intent '%s' "
                "(query_id='%s'). No template, registry file, LLM, or "
                "schema rule available. Details: %s",
                intent_type,
                query_entry.get("id", "?"),
                _tier4_exc,
            )
            raise NotImplementedError(
                f"[HybridOptimizer] No Cypher available for intent "
                f"'{query_entry.get('intent', 'unknown')}'. "
                f"All four tiers exhausted (template, registry file, LLM, schema generator)."
            )