# server.py  — KOS-PID Visual Query Server (dynamic image + PID selection)
# Place at KOS_PID/server.py.  Run: python server.py --port 8080
#
# PHASE 3.5 INTEGRATION:
#   Engineering rule violations (source='phase3_engineering_rules') are now
#   surfaced as first-class drawing issues:
#
#   _ENGINEERING_VIOLATIONS: 9 Phase 3.5 pattern types (CRITICAL/HIGH/MEDIUM)
#   _VIOLATION_SEVERITY:     per-pattern severity tier
#   _lookup_node_ids_for_issues Path C: queries engineering_rule_violation
#       Annotations which target Node instances directly (not LPS/PS).
#       Returns severity + explanation alongside node_id.
#   _parse_nodes: augmented with a Neo4j pass to pull functional_label,
#       has_rule_violations, rule_violation_count onto each node entry so
#       the UI can colour and annotate pump-labelled-as-tank nodes correctly.
#   /api/violations/<pid_id>: new endpoint returning per-PID violation summary.

from __future__ import annotations
import io, json, os, re, sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from flask import Flask, jsonify, request, send_file, send_from_directory
from agent.cli import build_agent

app = Flask(__name__, static_folder=str(PROJECT_ROOT / "ui"))

# ── Load store_root from config/storage.yaml ─────────────────────────────────
_store_root = ""
try:
    with open(PROJECT_ROOT / "config" / "storage.yaml") as f:
        _store_root = yaml.safe_load(f)["storage"]["store_root"]
    if not _store_root or not str(_store_root).strip():
        raise ValueError("store_root is empty in storage.yaml — cannot resolve file paths")
    print(f"[SERVER] Store root: {_store_root}")
except Exception as exc:
    print(f"[SERVER] Warning: storage.yaml — {exc}")

# ── Boot agent ────────────────────────────────────────────────────────────────
print("[SERVER] Initialising agent...")
_agent, _loader, _llm = build_agent()
print("[SERVER] Agent ready.")

# ── Enumerate PIDs from Neo4j ─────────────────────────────────────────────────
_pids: List[str] = []
_active_pid = "UNKNOWN"
try:
    with _loader.driver.session(database=_loader.database) as s:
        rows = s.run("MATCH (p:PID) RETURN p.pid_id AS pid_id ORDER BY p.pid_id").data()
        _pids = [r["pid_id"] for r in rows if r.get("pid_id")]
    if _pids:
        _active_pid = _pids[0]
    print(f"[SERVER] PIDs: {_pids}  active={_active_pid}")
except Exception as exc:
    print(f"[SERVER] Warning: PIDs — {exc}")


# ── Resolve image + graphml path from Neo4j ───────────────────────────────────
def _resolve_pid_paths(pid_id: str) -> Dict[str, str]:
    with _loader.driver.session(database=_loader.database) as s:
        row = s.run(
            "MATCH (:Plant)-[:HAS_SKID]->(:Skid)-[:HAS_PID]->(pid:PID {pid_id:$pid_id}) "
            "RETURN pid.graphml_path AS gml, pid.image_path AS img",
            pid_id=pid_id,
        ).single()
    if not row:
        raise ValueError(f"PID '{pid_id}' not found in Neo4j")
    gml = os.path.join(_store_root, row["gml"].replace("/", os.sep))
    img = os.path.join(_store_root, row["img"].replace("/", os.sep))
    # Security: prevent path traversal — verify both paths stay within store_root.
    _store_root_abs = Path(_store_root).resolve()
    try:
        Path(gml).resolve().relative_to(_store_root_abs)
    except ValueError:
        raise ValueError(f"GraphML path escapes store root — possible path traversal: {gml}")
    try:
        Path(img).resolve().relative_to(_store_root_abs)
    except ValueError:
        raise ValueError(f"Image path escapes store root — possible path traversal: {img}")
    if not os.path.exists(gml): raise FileNotFoundError(f"GraphML missing: {gml}")
    if not os.path.exists(img): raise FileNotFoundError(f"Image missing: {img}")
    return {"graphml": gml, "image": img}


# ── Parse GraphML → scaled node positions + Neo4j augmentation ───────────────
_node_cache: Dict[str, Dict] = {}
_NODE_CACHE_MAX = 50   # Evict oldest entry when this limit is reached

# Skid-type cache -- queried at most once per PID; constant for server lifetime.
_skid_type_cache: Dict[str, str] = {}


def _get_skid_type(pid_id: str) -> str:
    """Return skid_type for a PID; result is cached after first lookup."""
    if pid_id in _skid_type_cache:
        return _skid_type_cache[pid_id]
    skid_type = "CONDENSATE"
    try:
        with _loader.driver.session(database=_loader.database) as _sk_sess:
            _sk_row = _sk_sess.run(
                "MATCH (p:PID {pid_id:$pid})<-[:HAS_PID]-(s:Skid) "
                "RETURN s.skid_type AS st LIMIT 1",
                pid=pid_id,
            ).single()
        if _sk_row and _sk_row.get("st"):
            skid_type = str(_sk_row["st"])
    except Exception as exc:
        print(f"[SERVER] _get_skid_type({pid_id}): DB error, defaulting to CONDENSATE: {exc}")
    _skid_type_cache[pid_id] = skid_type
    return skid_type


def _fetch_neo4j_node_props(pid_id: str) -> Dict[str, Dict[str, Any]]:
    """
    Query Neo4j for per-node properties that are not in GraphML:
      - functional_label   (Phase 1 classify_equipment — 'pump' on small tanks)
      - has_rule_violations (Phase 4 violation summary — True when Phase 3.5 fired)
      - rule_violation_count
      - rule_violation_types (list of pattern_type strings)

    Returns dict keyed by node_id.
    """
    try:
        with _loader.driver.session(database=_loader.database) as s:
            rows = s.run(
                """
                MATCH (n:Node {pid_id: $pid_id})
                WHERE n.functional_label IS NOT NULL
                   OR n.has_rule_violations IS NOT NULL
                RETURN n.id                 AS node_id,
                       n.functional_label   AS functional_label,
                       n.has_rule_violations AS has_violations,
                       n.rule_violation_count AS violation_count,
                       n.rule_violation_types AS violation_types
                """,
                pid_id=pid_id,
            ).data()
        return {
            r["node_id"]: {
                "functional_label":   r.get("functional_label"),
                "has_violations":     bool(r.get("has_violations")),
                "violation_count":    int(r.get("violation_count") or 0),
                "violation_types":    r.get("violation_types") or [],
            }
            for r in rows
            if r.get("node_id")
        }
    except Exception as exc:
        print(f"[SERVER] _fetch_neo4j_node_props failed: {exc}")
        return {}


def _parse_nodes(pid_id: str) -> Dict[str, Any]:
    if pid_id in _node_cache:
        return _node_cache[pid_id]
    import xml.etree.ElementTree as ET
    paths  = _resolve_pid_paths(pid_id)
    prefix = "{http://graphml.graphdrawing.org/xmlns}"
    tree   = ET.parse(paths["graphml"])
    root   = tree.getroot()
    keys   = {k.get("id"): k.get("attr.name") for k in root.iter(f"{prefix}key")}
    graph  = root.find(f"{prefix}graph")
    if graph is None:
        return {"canvas": {"w": 0, "h": 0}, "nodes": []}

    all_nodes = []
    for n in graph.iter(f"{prefix}node"):
        d   = {keys.get(i.get("key"), i.get("key")): i.text
               for i in n.iter(f"{prefix}data")}
        lbl = d.get("label", "connector")
        try:
            xmin = float(str(d["xmin"]))
            ymin = float(str(d["ymin"]))
            xmax = float(str(d["xmax"]))
            ymax = float(str(d["ymax"]))
        except (KeyError, TypeError, ValueError):
            continue
        all_nodes.append({
            "id": n.get("id"), "label": lbl,
            "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax,
        })

    if not all_nodes:
        return {"canvas": {"w": 0, "h": 0}, "nodes": []}

    bg = [n for n in all_nodes if n["label"] == "background"]
    if bg:
        canvas_w = max(n["xmax"] for n in bg)
        canvas_h = max(n["ymax"] for n in bg)
    else:
        canvas_w = max(n["xmax"] for n in all_nodes)
        canvas_h = max(n["ymax"] for n in all_nodes)

    # Augment with Neo4j-sourced properties (functional_label, violations)
    neo4j_props = _fetch_neo4j_node_props(pid_id)

    # Node format: [id, label, xmin, ymin, w, h, functional_label, has_violations, violation_count]
    # functional_label and violation fields default to None/False/0 when not present.
    nodes = []
    for n in all_nodes:
        if n["label"] == "background":
            continue
        nid   = n["id"]
        props = neo4j_props.get(nid, {})
        nodes.append([
            nid,
            n["label"],
            round(n["xmin"], 2),
            round(n["ymin"], 2),
            round(n["xmax"] - n["xmin"], 2),
            round(n["ymax"] - n["ymin"], 2),
            props.get("functional_label"),       # index 6
            props.get("has_violations", False),  # index 7
            props.get("violation_count", 0),     # index 8
        ])

    result: Dict[str, Any] = {
        "canvas": {"w": canvas_w, "h": canvas_h},
        "nodes":  nodes,
    }
    # Bounded cache — evict oldest entry once the limit is reached so the
    # server doesn't grow unboundedly between re-ingestions.
    if len(_node_cache) >= _NODE_CACHE_MAX:
        oldest_key = next(iter(_node_cache))
        del _node_cache[oldest_key]
    _node_cache[pid_id] = result
    return result


# ── Phase 3.5: Engineering rule violation definitions ─────────────────────────

# All 9 Phase 3.5 pattern types — annotate Node instances directly via
# (Annotation {type:'engineering_rule_violation'})-[:ANNOTATES]->(Node)
_ENGINEERING_VIOLATIONS: frozenset = frozenset({
    "missing_check_valve",
    "missing_suction_strainer",
    "missing_isolation_valve",
    "tank_vent_position_violation",
    "tank_drain_position_violation",
    "control_valve_after_orifice",
    "missing_pressure_relief_valve",
    "missing_warming_coil",
    "missing_cooling_jacket",
})

_VIOLATION_SEVERITY: Dict[str, str] = {
    "missing_check_valve":           "CRITICAL",
    "missing_pressure_relief_valve": "CRITICAL",
    "missing_warming_coil":          "CRITICAL",
    "missing_cooling_jacket":        "CRITICAL",
    "missing_isolation_valve":       "HIGH",
    "tank_vent_position_violation":  "HIGH",
    "control_valve_after_orifice":   "HIGH",
    "missing_suction_strainer":      "MEDIUM",
    "tank_drain_position_violation": "MEDIUM",
}

_VIOLATION_FRIENDLY: Dict[str, str] = {
    "missing_check_valve":           "Missing check valve (backflow protection)",
    "missing_suction_strainer":      "Missing suction strainer (debris protection)",
    "missing_isolation_valve":       "Missing isolation valve (maintenance access)",
    "tank_vent_position_violation":  "Tank vent not at highest point",
    "tank_drain_position_violation": "Tank drain not at lowest point",
    "control_valve_after_orifice":   "Control valve downstream of orifice plate",
    "missing_pressure_relief_valve": "Missing pressure relief valve (overpressure)",
    "missing_warming_coil":          "Missing warming coil (cryogenic service)",
    "missing_cooling_jacket":        "Missing cooling jacket (high-temperature service)",
}

# ── Highlight extraction ──────────────────────────────────────────────────────
_NODE_ID_FIELDS = {
    # Core node id aliases used across all query generators
    "node_id", "valve_id", "interface_id", "tank_id",
    "branching_valve", "orphan_id", "symbol_id",
    "affected_equipment",   # Phase 3.5 violation target
    "equipment_id",         # Phase 5 engineering_correctness queries
    # Connectivity / topology
    "neighbour_id",         # _connectivity_topology: what nodes connected to X
    "orphan_node_id",       # isolation_reachability: orphan node list
    # Structural / junction
    "junction_symbol",      # segment_junction_topology: junction centre node
    # Rarity / pattern / annotation targets
    "target_id",            # redundancy_patterns targets, generic annotation target
    # Engineering correctness — pump/vessel specific aliases
    "pump_id",              # engineering_correctness pump queries
    "vessel_id",            # engineering_correctness vessel queries
    "pump_without_isolation",   # pumps lacking isolation valve
    "pump_without_check_valve", # pumps lacking downstream check valve
    # Cross-domain / instrument
    "instrument_id",        # cross_domain instrument anomaly queries
    # Additional node-id aliases seen in Phase-5 and corrected cypher files
    "boundary_node", "orphan_boundary_node",
    "equipment", "connected_equipment", "isolated_equipment", "isolated_symbol",
    "equipment_a", "equipment_b", "dead_end_node", "seed_equipment",
    "tag_id", "isolated_line", "left_interface", "right_interface",
    # Topology corrected pack — inventory / topology corrected queries
    "equipment_tag",        # corrected_01/02 inventory: e.id AS equipment_tag
    "from_equipment",       # corrected_02 path queries: a.id AS from_equipment
    "to_equipment",         # corrected_02 path queries: b.id AS to_equipment
    # Directionality / flow
    "arrow_id",             # arrow evidence queries
    "arrow",                # directionality arrow listing
    "orphan_arrow",         # directionality orphan arrow query
    # Generic bare id — used by many Phase 5 cypher files as n.id or lps.id
    # JS drawIds only renders IDs that exist in the nodes array, so non-node
    # IDs (annotation IDs etc.) are silently ignored on the canvas.
    "id",
}

# Deterministic priority when selecting a single representative node id
# from each record (used by tooltip context builders).
_NODE_ID_FIELD_PRIORITY = (
    "node_id", "valve_id", "interface_id", "tank_id",
    "branching_valve", "orphan_id", "symbol_id",
    "affected_equipment", "equipment_id",
    "neighbour_id", "orphan_node_id",
    "junction_symbol",
    "target_id",
    "pump_id", "vessel_id",
    "pump_without_isolation", "pump_without_check_valve",
    "instrument_id",
    "boundary_node", "orphan_boundary_node",
    "equipment", "connected_equipment", "isolated_equipment", "isolated_symbol",
    "equipment_a", "equipment_b", "dead_end_node", "seed_equipment",
    "tag_id", "isolated_line", "left_interface", "right_interface",
    "equipment_tag", "from_equipment", "to_equipment",
    "arrow_id", "arrow", "orphan_arrow",
    "id",
)

_NODE_ID_FIELD_SET = {f.lower() for f in _NODE_ID_FIELDS}
_LABEL_FIELDS = {
    "type", "label", "node_type", "symbol_type",
    "structural_type", "node_label",
    # Common aliases across Phase-5/corrected queries
    "equipment_type", "equipment_role", "valve_type", "vessel_type",
    "boundary_label", "drawing_label",
    "equipment_a_type", "equipment_b_type", "type_a", "type_b",
}
_LABEL_MAP = {
    "valve": "valve", "valves": "valve",
    "tank": "tank", "tanks": "tank",
    "instrumentation": "instrumentation", "instrument": "instrumentation",
    "inlet/outlet": "inlet/outlet", "inlet": "inlet/outlet", "outlet": "inlet/outlet",
    "general": "general", "arrow": "arrow",
    "connector": "connector", "crossing": "crossing",
    "inferred_check_valve": "inferred_check_valve",
}

# LPS record field names (ids contain "__" separator: "valve94__crossing123")
_LPS_ID_FIELDS = {
    "lps_id", "pipe_run", "logical_segment", "segment_id", "lps", "pipe_line_id",
    "via_segment",          # connectivity_topology upstream/downstream: lps used for direction
    "logical_segment_id",   # line_attributes queries returning LPS
    "pipe_run_without_direction",  # directionality queries for unresolved pipe runs
    "pipe_line",            # flow_coverage gap queries: lps.id AS pipe_line
    "via_lps", "via_logical_segment", "from_lps", "to_lps",
    "logical_pipe_segment", "pipe_segment",
    "connected_lps",        # topology corrected_02: lps.id AS connected_lps
    # Generic bare id also checked here — value with "__" separator → LPS
    "id",
}
_LPS_ID_FIELD_SET = {f.lower() for f in _LPS_ID_FIELDS}

# Record fields whose VALUE is a LIST of node ids (ordered path — used for polyline tracing)
_PATH_NODE_FIELDS = {"path_nodes", "node_path", "trace_nodes", "via_nodes", "node_ids", "ids"}
_PATH_NODE_FIELD_SET = {f.lower() for f in _PATH_NODE_FIELDS}

# Record fields whose VALUE is a LIST of node ids (unordered bag — extracted as individual nodes,
# NOT treated as a polyline path to avoid drawing spurious connector lines between
# unrelated items returned by collect() aggregate queries).
_AGGREGATE_NODE_FIELDS = {
    "examples",         # collect(DISTINCT n.id)[0..5] AS examples (consistency/connectivity)
    "example_ids",      # alternate alias
    "connected_to",     # inventory/valve queries: collect(DISTINCT nb.id) AS connected_to
    "connects_to",      # external_interfaces: collect(DISTINCT nb.id) AS connects_to
    "members",          # generic bag of member node ids
    # Additional aggregate aliases used by corrected query packs
    "connected_equipment", "isolated_equipment", "equipments",
    "ids", "node_ids", "endpoints", "endpoint_nodes",
    "left_component", "right_component", "other_endpoints",
    # Directionality corrected pack: lists of arrow node IDs
    "direction_arrows",  # corrected_06_direction_indication_between_components
    "arrow_ids",         # corrected_06_pipe_runs_explicitly_show_flow_direction
    # Instrument / topology corrected packs
    "instruments",       # q3_11_instruments_grouped_their_component_id: list of instr IDs
}
_AGGREGATE_NODE_FIELD_SET = {f.lower() for f in _AGGREGATE_NODE_FIELDS}


def _iter_record_entries(record: Dict[str, Any]):
    """
    Yield normalized record entries as (full_key_lower, base_key_lower, value).

    Handles unaliased Cypher keys like "v.id" or "r.trace_nodes" by exposing
    the base key ("id", "trace_nodes") in addition to the full key.
    """
    for key, value in record.items():
        if not isinstance(key, str):
            continue
        full = key.strip().lower()
        if not full:
            continue
        base = full.rsplit(".", 1)[-1]
        yield full, base, value


def _iter_field_values(record: Dict[str, Any], field_name: str):
    needle = str(field_name).strip().lower()
    if not needle:
        return
    for full, base, value in _iter_record_entries(record):
        if full == needle or base == needle:
            yield value


def _first_scalar_value(record: Dict[str, Any], *field_names: str) -> Any:
    for field_name in field_names:
        for value in _iter_field_values(record, field_name):
            if value is None or isinstance(value, (list, dict)):
                continue
            txt = str(value).strip()
            if not txt or txt == "None":
                continue
            return value
    return None


def _pid_node_universe(pid_id: str) -> set:
    """Return all drawable node IDs for this PID (from GraphML cache/parser)."""
    if not pid_id or pid_id == "UNKNOWN":
        return set()
    try:
        parsed = _parse_nodes(pid_id)
        return {
            str(n[0]).strip()
            for n in parsed.get("nodes", [])
            if isinstance(n, list) and n and isinstance(n[0], str) and str(n[0]).strip()
        }
    except Exception:
        return set()


def _is_valid_node_id(candidate: str, node_universe: set) -> bool:
    if not candidate or "__" in candidate:
        return False
    if node_universe:
        return candidate in node_universe
    return True


def _first_node_id_from_record(record: Dict[str, Any], node_universe: set) -> Optional[str]:
    # Prefer known logical aliases first.
    for field_name in _NODE_ID_FIELD_PRIORITY:
        for raw in _iter_field_values(record, field_name):
            if not isinstance(raw, str):
                continue
            candidate = raw.strip()
            if _is_valid_node_id(candidate, node_universe):
                return candidate

    # Fall back to generic/unaliased id-like keys.
    for full, base, raw in _iter_record_entries(record):
        if not isinstance(raw, str):
            continue
        candidate = raw.strip()
        if not candidate:
            continue
        key_idish = (
            full == "id" or base == "id" or ".id" in full
            or full.endswith("_id") or base.endswith("_id")
        )
        if key_idish and _is_valid_node_id(candidate, node_universe):
            return candidate

    # Path lists: pick the last valid node as the anchor.
    for field_name in _PATH_NODE_FIELDS:
        for raw in _iter_field_values(record, field_name):
            if not isinstance(raw, list) or not raw:
                continue
            for item in reversed(raw):
                if not isinstance(item, str):
                    continue
                candidate = item.strip()
                if _is_valid_node_id(candidate, node_universe):
                    return candidate

    return None


def _extract_ids_and_paths(records: List[Dict[str, Any]], node_universe: set):
    """
    Extract drawable node ids, LPS ids, and path-node lists from records.

    Handles unaliased Cypher keys (e.g., "v.id", "r.trace_nodes").
    """
    node_ids: List[str] = []
    lps_ids: List[str] = []
    path_lists: List[List[str]] = []

    for rec in records:
        if not isinstance(rec, dict):
            continue

        for full, base, raw in _iter_record_entries(rec):
            is_node_field  = full in _NODE_ID_FIELD_SET  or base in _NODE_ID_FIELD_SET
            is_lps_field   = full in _LPS_ID_FIELD_SET   or base in _LPS_ID_FIELD_SET
            is_path_field  = full in _PATH_NODE_FIELD_SET or base in _PATH_NODE_FIELD_SET
            is_agg_field   = full in _AGGREGATE_NODE_FIELD_SET or base in _AGGREGATE_NODE_FIELD_SET
            key_idish = (
                full == "id" or base == "id" or ".id" in full
                or full.endswith("_id") or base.endswith("_id")
            )

            if isinstance(raw, str):
                value = raw.strip()
                if not value:
                    continue

                # LPS ids contain "__" by convention.
                if "__" in value:
                    if is_lps_field or key_idish:
                        lps_ids.append(value)
                    continue

                if (is_node_field or key_idish) and _is_valid_node_id(value, node_universe):
                    node_ids.append(value)

            elif isinstance(raw, list) and is_path_field:
                # Ordered path list — used for polyline pipe-trace rendering.
                path = [str(x).strip() for x in raw if isinstance(x, str) and str(x).strip()]
                if not path:
                    continue
                path_lists.append(path)
                for value in path:
                    if "__" in value:
                        lps_ids.append(value)
                    elif _is_valid_node_id(value, node_universe):
                        node_ids.append(value)

            elif isinstance(raw, list) and (is_agg_field or is_node_field):
                # Unordered bag of node IDs (e.g. examples, connected_to).
                # Add each valid element to node_ids but do NOT create a
                # path_list entry so no spurious connector polyline is drawn.
                for item in raw:
                    if not isinstance(item, str):
                        continue
                    v = item.strip()
                    if not v:
                        continue
                    if "__" in v:
                        # Aggregate fields may return LPS IDs even when alias is generic
                        # (e.g., ids, segments, endpoint_nodes). Keep all LPS-shaped IDs.
                        lps_ids.append(v)
                    elif _is_valid_node_id(v, node_universe):
                        node_ids.append(v)

    return (
        list(dict.fromkeys(node_ids)),
        list(dict.fromkeys(lps_ids)),
        path_lists,
    )


def _node_ids_by_functional_label(pid_id: str, functional_label: str) -> List[str]:
    if not pid_id or pid_id == "UNKNOWN" or not functional_label:
        return []
    wanted = functional_label.strip().lower()
    try:
        parsed = _parse_nodes(pid_id)
        ids = [
            str(n[0]).strip()
            for n in parsed.get("nodes", [])
            if isinstance(n, list)
            and len(n) >= 7
            and isinstance(n[0], str)
            and str(n[0]).strip()
            and str(n[6] or "").strip().lower() == wanted
        ]
        return list(dict.fromkeys(ids))
    except Exception:
        return []


def _infer_inventory_highlight(
    records: List[Dict[str, Any]],
    question: str,
    pid_id: str,
) -> Optional[Dict[str, Any]]:
    q = (question or "").lower()

    # Pump is a functional role (stored as tank with functional_label='pump').
    if "pump" in q:
        pump_ids = _node_ids_by_functional_label(pid_id, "pump")
        if pump_ids:
            return {"mode": "ids", "node_ids": pump_ids, "labels": []}

    labels: List[str] = []
    if any(w in q for w in ["valve", "check valve", "check valves"]):
        labels.append("valve")
    if any(w in q for w in ["tank", "vessel"]):
        labels.append("tank")
    if any(w in q for w in ["instrument", "instruments", "instrumentation"]):
        labels.append("instrumentation")
    if "arrow" in q:
        labels.append("arrow")
    if any(w in q for w in ["external", "interface", "interfaces", "inlet", "outlet"]):
        labels.append("inlet/outlet")
    if "inline equipment" in q:
        labels.extend(["valve", "tank", "instrumentation", "inlet/outlet"])
    if "symbols by type" in q or ("symbol" in q and "type" in q):
        labels.extend(["connector", "valve", "tank", "instrumentation", "arrow", "inlet/outlet"])

    # Infer from aggregate row keys/values when question text is generic.
    key_label_hints = {
        "tank_count": "tank",
        "arrow_node_count": "arrow",
        "valve_count": "valve",
        "instrument_count": "instrumentation",
        "interface_count": "inlet/outlet",
    }
    for rec in records:
        for full, base, value in _iter_record_entries(rec):
            hint = key_label_hints.get(base) or key_label_hints.get(full)
            if hint:
                labels.append(hint)
            if base in _LABEL_FIELDS or full in _LABEL_FIELDS:
                mapped = _LABEL_MAP.get(str(value or "").lower().strip())
                if mapped:
                    labels.append(mapped)

    labels = list(dict.fromkeys(filter(None, labels)))
    if labels:
        return {"mode": "labels", "node_ids": [], "labels": labels}
    return None

# Intents that produce pipe-trace highlights.  Only activated when records
# contain NO individual node IDs — aggregate/coverage queries like
# "What is the flow direction coverage?"  List queries that include node_ids
# (e.g. "show valves with SEEDED flow") fall through to the node-id path.
_PIPE_INTENTS = {"flow_coverage", "line_attributes", "flow_direction", "directionality_drawn"}
# flow_direction is included so that queries returning LPS ids (e.g. "show
# unresolved pipe lines") render pipe traces instead of falling through to the
# arrow-label fallback.  Arrow-node queries still take the ids-path first
# because arrow node IDs (e.g. arrow102) are extracted before the LPS check.
# directionality_drawn is included so that "show pipe runs without direction"
# queries (which return pipe_run_without_direction LPS ids) render as coloured
# pipe traces.  Queries returning individual arrow node ids still take the
# ids path first (arrow IDs are extracted before the LPS check fires).

_INTENT_LBLS = {
    "valve_placement":        ["valve"],
    "instrument_attachment":  ["instrumentation"],
    # engineering_inventory intentionally omitted: count-only results have no label field
    # so falling back to all 5 label types highlights every symbol on the canvas.
    # When node IDs are returned, the mode='ids' / label-aggregate steps handle it.
    "external_interfaces":    ["inlet/outlet"],
    # drawing_consistency / engineering_correctness / isolation_reachability:
    #   handled by quality_intents path in _highlight (calls _lookup_node_ids_for_issues).
    #   Do NOT add label fallbacks here — they would never be reached.
    "flow_direction":         ["arrow"],   # fallback when no IDs/LPS for arrow queries
    "directionality_drawn":   ["arrow"],   # arrow evidence/orphan queries
    "segment_junction_topology": ["crossing"],
    # connectivity_topology: intentionally NOT listed — too broad; show mode='none'
    # when a connectivity query returns nothing rather than blanketing all nodes.
    # graph_reachability: NOT listed — count/structural queries; no per-node fallback.
}

_INTENT_REASON: Dict[str, str] = {
    "valve_placement":        "Valve symbol — matched by valve query",
    "instrument_attachment":  "Instrument symbol — matched by instrument query",
    "engineering_inventory":  "Equipment symbol — matched by inventory query",
    "external_interfaces":    "External interface — drawing boundary connection",
    "drawing_consistency":    "Quality issue — flagged by consistency check",
    "engineering_correctness":"Engineering check — topology review",
    "flow_direction":         "Flow direction symbol",
    "flow_coverage":          "Pipe line with unresolved flow direction",
    "redundancy_patterns":    "Redundancy/rarity pattern",
    "annotation_requests":    "Open annotation request",
    "isolation_reachability": "Isolated or unreachable symbol",
    "connectivity_topology":  "Topology / connectivity query result",
    "engineering_violations": "Engineering rule violation — requires engineer review",
    "cross_domain":           "Cross-domain query — spans multiple entity types",
    "line_attributes":        "Pipe segment / line attribute query",
    "segment_junction_topology": "Segment junction — crossing or branch point",
    "directionality_drawn":   "Flow direction drawn on this symbol",
    "graph_reachability":     "Graph reachability / connectivity analysis",
}

_DETAIL_FIELDS = {
    "type":               "Symbol type",
    "connections":        "Pipe connections",
    "flow_state":         "Flow status",
    "flow_direction":     "Flow direction",
    "flow_confidence":    "Flow confidence",
    "rarity":             "Rarity score",
    "pipe_connections":   "Pipe connections",
    "logical_segment":    "Pipe line",
    "anomaly_type":       "Issue type",
    "detail":             "Detail",
    "status":             "Status",
    "width":              "Symbol width",
    "height":             "Symbol height",
    # Engineering correctness / violations
    "equipment_role":     "Equipment role",
    "rule_type":          "Rule type",
    "review_status":      "Review status",
    "issue_detail":       "Issue detail",
    # Flow / directionality corrected queries
    "drawn_flow_state":   "Drawn flow state",
    "phase4_flow_state":  "Inferred flow state",
    "phase4_direction":   "Inferred direction",
    "phase4_hint":        "Phase-4 hint",
    "confidence":         "Evidence confidence",
    # External interfaces / boundary corrected queries
    "boundary_connectivity": "Boundary connections",
    "node_connectivity":  "Pipe connectivity",
    "pipe_connectivity":  "Pipe connectivity",
    "drawing_location":   "Location on drawing",
    # Topology / path corrected queries
    "lps_connections":    "LPS connections",
    "hops":               "Path hops",
    "lps_hop_count":      "LPS hops",
    "degree":             "Degree (connections)",
    "pipe_degree":        "Pipe degree",
    "actual_degree":      "Actual connections",
}

# Value-level translations: maps raw Neo4j property values to engineer-friendly display strings.
_FLOW_STATE_DISPLAY: Dict[str, str] = {
    "SEEDED":     "Confirmed on drawing",
    "PROPAGATED": "Inferred from adjacent pipe",
    "UNKNOWN":    "Not determined",
}
_FLOW_DIRECTION_DISPLAY: Dict[str, str] = {
    "FORWARD": "Downstream →",
    "REVERSE": "← Upstream",
}
_FIELD_VALUE_DISPLAY: Dict[str, Dict[str, str]] = {
    "flow_state":     _FLOW_STATE_DISPLAY,
    "flow_direction": _FLOW_DIRECTION_DISPLAY,
}

# ── Annotation issue tiers ────────────────────────────────────────────────────

_DEFECT_ISSUES: set = {
    "orphan_node",
    "endpoint_count_mismatch",
    "endpoint_collision",
    # Phase 3.5 engineering rule violations are also defects — CRITICAL/HIGH ones
    # block FSM propagation and require engineer review.
    *_ENGINEERING_VIOLATIONS,
}

_PIPE_SEGMENT_DEFECTS: set = {
    "pipe_segment_no_logical_mapping",
}
_PIPE_SEGMENT_INFO: set = {
    "dead_end_pipe_segment",
}

_TOPOLOGY_ISSUES: set = {
    "structural_branch", "structural_t_junction", "structural_high_degree",
    "large_manifold_node", "pipe_junction", "rare_motif_local",
    "structural_pattern_rarity",
}

_SPATIAL_NODE_ISSUES: set = _DEFECT_ISSUES | _TOPOLOGY_ISSUES
_NODE_LEVEL_ISSUES = _DEFECT_ISSUES   # legacy alias

_ISSUE_REASON_MAP: Dict[str, str] = {
    # ── Genuine defects ──────────────────────────────────────────────────
    "orphan_node":
        "Symbol has no pipe connections — it is floating and unconnected",
    "endpoint_count_mismatch":
        "This symbol has a different number of connections than expected",
    "endpoint_collision":
        "Two pipe runs end at exactly the same point — possible overlapping nozzles",
    # ── Phase 3.5 engineering rule violations ────────────────────────────
    "missing_check_valve":
        "Pump has no check valve within reach downstream — backflow risk",
    "missing_suction_strainer":
        "Pump has no suction strainer within reach upstream — debris risk",
    "missing_isolation_valve":
        "Component has no isolation valve — cannot be taken out of service safely",
    "tank_vent_position_violation":
        "Tank vent is not at the highest point — atmospheric equalisation may fail",
    "tank_drain_position_violation":
        "Tank drain is not at the lowest point — tank may not drain completely",
    "control_valve_after_orifice":
        "Control valve is downstream of the orifice plate — disturbs flow measurement",
    "missing_pressure_relief_valve":
        "Pressure vessel has no relief valve — overpressure protection missing",
    "missing_warming_coil":
        "Equipment in cryogenic service has no warming coil — seal ice-up risk",
    "missing_cooling_jacket":
        "Equipment in high-temperature service has no cooling jacket — bearing damage risk",
    # ── Normal topology (informational) ─────────────────────────────────
    "structural_branch":         "Branch point — normal 3-way pipe junction",
    "structural_t_junction":     "T-junction — normal pipe branch",
    "structural_high_degree":    "High-degree junction — 4+ connections (normal for manifolds/tanks)",
    "large_manifold_node":       "Large manifold — normal high-connection header",
    "pipe_junction":             "Pipe junction point",
    "rare_motif_local":          "Rare local topology pattern",
    "structural_pattern_rarity": "Unusual structural pattern",
    # ── Pipe-level issues ────────────────────────────────────────────────
    "pipe_segment_no_logical_mapping":
        "Disconnected pipe stub — this connector belongs to a pipe run that has "
        "no start or end equipment (likely a nozzle duplicated during export)",
    "dead_end_pipe_segment":
        "Open-ended pipe stub — one end of this run has no connected equipment "
        "(may be a drain, vent, or graphml export gap)",
    # ── LPS-level ────────────────────────────────────────────────────────
    "lps_low_confidence_evidence":
        "Flow direction is uncertain on this pipe line — not enough arrow evidence",
}

_ISSUE_DISPLAY_NAME: Dict[str, str] = {
    "orphan_node":                      "Unconnected symbol",
    "endpoint_count_mismatch":          "Wrong connection count",
    "endpoint_collision":               "Overlapping pipe ends",
    "pipe_segment_no_logical_mapping":  "Disconnected pipe stub",
    "dead_end_pipe_segment":            "Open-ended pipe stub",
    "structural_branch":                "3-way junction",
    "structural_t_junction":            "T-junction",
    "structural_high_degree":           "High-connection node",
    "large_manifold_node":              "Large manifold",
    "pipe_junction":                    "Pipe junction",
    "rare_motif_local":                 "Unusual pattern",
    "structural_pattern_rarity":        "Unusual pattern",
    "lps_low_confidence_evidence":      "Uncertain flow direction",
    # Phase 3.5
    "missing_check_valve":              "Missing check valve",
    "missing_suction_strainer":         "Missing suction strainer",
    "missing_isolation_valve":          "Missing isolation valve",
    "tank_vent_position_violation":     "Vent position wrong",
    "tank_drain_position_violation":    "Drain position wrong",
    "control_valve_after_orifice":      "Valve after orifice",
    "missing_pressure_relief_valve":    "Missing relief valve",
    "missing_warming_coil":             "Missing warming coil",
    "missing_cooling_jacket":           "Missing cooling jacket",
}

_CATEGORY_DISPLAY: Dict[str, str] = {
    "defect":           "Drawing issue",
    "pipe-run defect":  "Pipe connection gap",
    "topology":         "Topology (informational)",
    "safety-critical":  "Safety violation (CRITICAL)",
    "safety-high":      "Safety violation (HIGH)",
    "safety-medium":    "Safety violation (MEDIUM)",
}


# ── Answer text sanitiser ─────────────────────────────────────────────────────
_ANSWER_REPLACEMENTS = [
    # Phase 3.5 engineering terms
    ("inferred_check_valve",            "inferred check valve"),
    ("functional_label",                "equipment role"),
    ("engineering_rule_violation",      "engineering rule violation"),
    ("missing_check_valve",             "missing check valve"),
    ("missing_suction_strainer",        "missing suction strainer"),
    ("missing_isolation_valve",         "missing isolation valve"),
    ("tank_vent_position_violation",    "tank vent position issue"),
    ("tank_drain_position_violation",   "tank drain position issue"),
    ("control_valve_after_orifice",     "control valve after orifice"),
    ("missing_pressure_relief_valve",   "missing pressure relief valve"),
    ("missing_warming_coil",            "missing warming coil"),
    ("missing_cooling_jacket",          "missing cooling jacket"),
    ("phase3_engineering_rules",        "engineering rule checker"),
    ("skid_type",                       "skid type"),
    ("semantic_source",                 "skid type source"),
    # Existing replacements
    ("pipe_segment_no_logical_mapping", "disconnected pipe stub"),
    ("pipe segment no logical mapping", "disconnected pipe stub"),
    ("no logical mapping",              "no connected equipment on both ends"),
    ("lps_low_confidence_evidence",     "uncertain flow direction"),
    ("low_confidence_evidence",         "low-confidence flow evidence"),
    ("endpoint_count_mismatch",         "connection count mismatch"),
    ("endpoint_collision",              "overlapping pipe ends"),
    ("orphan_node",                     "unconnected symbol"),
    ("dead_end_pipe_segment",           "open-ended pipe stub"),
    ("structural_high_degree",          "high-connection node"),
    ("structural_t_junction",           "T-junction node"),
    ("structural_branch",               "branch junction node"),
    ("large_manifold_node",             "large manifold node"),
    ("pipe runs with no pipe line mapping", "disconnected pipe stubs"),
    ("Pipe runs with no pipe line mapping", "Disconnected pipe stubs"),
    ("pipe run with no pipe line mapping",  "disconnected pipe stub"),
    ("no pipe line mapping",            "no connected pipe line"),
    ("LogicalPipeSegment",              "pipe line"),
    ("logical pipe segment",            "pipe line"),
    ("PipeSegment",                     "pipe segment"),
    ("pipe-run defect",                 "pipe connection gap"),
    ("Annotation type:",                "Issue:"),
    ("annotation_type",                 "issue type"),
    ("pid_id",                          "drawing ID"),
    ("phase4_hint",                     "flow hint"),
    ("propagation_blocked",             "flow propagation blocked"),
    # Flow state raw values (safety net — LLM or explainer may emit these)
    ("flow_state='SEEDED'",             "flow direction confirmed on drawing"),
    ("flow_state='PROPAGATED'",         "flow direction inferred from adjacent pipe"),
    ("flow_state='SEEDED_UNKNOWN'",     "flow direction unclear (conflicting arrows)"),
    ("flow_state='BLOCKED'",            "flow direction not applicable (structurally isolated)"),
    ("flow_state='UNKNOWN'",            "flow direction not determined"),
    ("flow_state = 'SEEDED'",           "flow direction confirmed on drawing"),
    ("flow_state = 'PROPAGATED'",       "flow direction inferred from adjacent pipe"),
    ("flow_state = 'SEEDED_UNKNOWN'",   "flow direction unclear (conflicting arrows)"),
    ("flow_state = 'BLOCKED'",          "flow direction not applicable (structurally isolated)"),
    ("flow_state = 'UNKNOWN'",          "flow direction not determined"),
    (" SEEDED_UNKNOWN ",                " conflicting arrows — direction unclear "),
    (" BLOCKED ",                       " structurally isolated "),
    (" SEEDED ",                        " confirmed on drawing "),
    (" PROPAGATED ",                    " inferred from adjacent pipe "),
    ("'SEEDED_UNKNOWN'",                "'conflicting arrows — direction unclear'"),
    ("'BLOCKED'",                       "'structurally isolated'"),
    ("'SEEDED'",                        "'confirmed on drawing'"),
    ("'PROPAGATED'",                    "'inferred from adjacent pipe'"),
]

def _sanitise_answer(text: str) -> str:
    for internal, friendly in _ANSWER_REPLACEMENTS:
        text = text.replace(internal, friendly)
    return text


# ── Node ID + issue lookup ────────────────────────────────────────────────────

def _lookup_node_ids_for_issues(
    issue_types: List[str],
    pid_id: str,
    *,
    allow_topology: bool = False,
) -> List[Dict[str, Any]]:
    """
    Fetch Node IDs flagged by the given annotation types for a PID.

    Three paths:
      Path A — Node-level structural annotations (orphan, endpoint mismatch, etc.)
      Path B — PipeSegment-level annotations traversed via CONTAINS to member Nodes
      Path C — Phase 3.5 engineering rule violations (annotate Node directly,
                include severity + explanation from the Annotation node)
    """
    if allow_topology:
        node_types = [t for t in issue_types if t in _SPATIAL_NODE_ISSUES
                      and t not in _ENGINEERING_VIOLATIONS]
    else:
        node_types = [t for t in issue_types if t in _DEFECT_ISSUES
                      and t not in _ENGINEERING_VIOLATIONS]

    pipe_types = [t for t in issue_types if t in _PIPE_SEGMENT_DEFECTS]
    if allow_topology:
        pipe_types += [t for t in issue_types if t in _PIPE_SEGMENT_INFO]

    # Path C: Phase 3.5 engineering rule violations
    violation_types = [t for t in issue_types if t in _ENGINEERING_VIOLATIONS]

    if not node_types and not pipe_types and not violation_types:
        print(f"[SERVER] _lookup_node_ids_for_issues: no spatial issues in {issue_types} "
              f"(allow_topology={allow_topology})")
        return []

    results: List[Dict[str, Any]] = []
    seen: set = set()

    try:
        with _loader.driver.session(database=_loader.database) as sess:

            # Path A: direct Node-level structural annotations
            if node_types:
                rows_a = sess.run(
                    "MATCH (a:Annotation)-[:ANNOTATES]->(n:Node) "
                    "WHERE a.pid_id = $pid AND a.type IN $types "
                    "RETURN DISTINCT n.id AS node_id, n.label AS label, "
                    "a.type AS issue_type "
                    "ORDER BY a.type, n.id LIMIT 200",
                    pid=pid_id, types=node_types,
                ).data()
                print(f"[SERVER] Path A ({pid_id}, {node_types}): {len(rows_a)} rows")
                for r in rows_a:
                    key = (r["node_id"], r["issue_type"])
                    if key not in seen:
                        seen.add(key)
                        results.append(r)

            # Path B: PipeSegment-level annotations → member Nodes via CONTAINS
            if pipe_types:
                rows_b = sess.run(
                    "MATCH (a:Annotation)-[:ANNOTATES]->(ps:PipeSegment)"
                    "-[:CONTAINS]->(n:Node) "
                    "WHERE a.pid_id = $pid AND a.type IN $types "
                    "RETURN DISTINCT n.id AS node_id, n.label AS label, "
                    "a.type AS issue_type "
                    "ORDER BY a.type, n.id LIMIT 400",
                    pid=pid_id, types=pipe_types,
                ).data()
                print(f"[SERVER] Path B ({pid_id}, {pipe_types}): {len(rows_b)} rows")
                for r in rows_b:
                    key = (r["node_id"], r["issue_type"])
                    if key not in seen:
                        seen.add(key)
                        results.append(r)

            # Path C: Phase 3.5 engineering rule violations → Node directly
            # Annotation has type='engineering_rule_violation' and pattern_type=<violation>
            # Also returns severity + explanation for the UI
            if violation_types:
                rows_c = sess.run(
                    "MATCH (a:Annotation {pid_id: $pid, type: 'engineering_rule_violation'})"
                    "-[:ANNOTATES]->(n:Node) "
                    "WHERE a.pattern_type IN $types "
                    "RETURN DISTINCT n.id AS node_id, n.label AS label, "
                    "a.pattern_type AS issue_type, "
                    "a.severity     AS severity, "
                    "a.explanation  AS explanation, "
                    "a.skid_type    AS skid_type "
                    "ORDER BY a.severity, n.id LIMIT 200",
                    pid=pid_id, types=violation_types,
                ).data()
                print(f"[SERVER] Path C ({pid_id}, {violation_types}): {len(rows_c)} rows")
                for r in rows_c:
                    key = (r["node_id"], r["issue_type"])
                    if key not in seen:
                        seen.add(key)
                        results.append(r)

    except Exception as exc:
        print(f"[SERVER] _lookup_node_ids_for_issues failed: {exc}")
        return []

    return results


def _lookup_node_ids_for_rarity(
    pid_id: str,
    ann_types: Optional[List[str]] = None,
    pattern_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Resolve rarity/redundancy annotations to drawable Node IDs.

    Supports annotations attached either directly to Node or to PipeSegment
    (expanded via PipeSegment-[:CONTAINS]->Node).
    """
    ann_types = [t for t in (ann_types or []) if t]
    pattern_types = [p for p in (pattern_types or []) if p and p != "__summary__"]
    try:
        with _loader.driver.session(database=_loader.database) as sess:
            rows = sess.run(
                "MATCH (a:Annotation {pid_id:$pid}) "
                "WHERE ($ann_types = [] OR a.type IN $ann_types) "
                "  AND ($pattern_types = [] OR coalesce(a.pattern_type,'') IN $pattern_types) "
                "OPTIONAL MATCH (a)-[:ANNOTATES]->(n:Node) "
                "OPTIONAL MATCH (a)-[:ANNOTATES]->(ps:PipeSegment)-[:CONTAINS]->(cn:Node) "
                "WITH a, coalesce(n.id, cn.id) AS node_id "
                "WHERE node_id IS NOT NULL "
                "RETURN DISTINCT node_id AS node_id, "
                "       coalesce(a.pattern_type, a.type) AS issue_type, "
                "       a.rarity_label AS rarity_label, "
                "       a.rarity_score AS rarity_score, "
                "       a.hitl_severity AS severity "
                "LIMIT 800",
                pid=pid_id,
                ann_types=ann_types,
                pattern_types=pattern_types,
            ).data()
        return rows
    except Exception as exc:
        print(f"[SERVER] _lookup_node_ids_for_rarity failed: {exc}")
        return []


def _lookup_node_ids_by_annotation_category(pid_id: str, category: str) -> List[str]:
    if not pid_id or not category:
        return []
    try:
        with _loader.driver.session(database=_loader.database) as sess:
            rows = sess.run(
                "MATCH (a:Annotation {pid_id:$pid}) "
                "WHERE toLower(coalesce(a.category,'')) = toLower($cat) "
                "OPTIONAL MATCH (a)-[:ANNOTATES]->(n:Node) "
                "OPTIONAL MATCH (a)-[:ANNOTATES]->(ps:PipeSegment)-[:CONTAINS]->(cn:Node) "
                "WITH coalesce(n.id, cn.id) AS node_id "
                "WHERE node_id IS NOT NULL "
                "RETURN DISTINCT node_id "
                "LIMIT 800",
                pid=pid_id,
                cat=category,
            ).data()
        return list(dict.fromkeys(str(r.get("node_id") or "").strip() for r in rows if r.get("node_id")))
    except Exception as exc:
        print(f"[SERVER] _lookup_node_ids_by_annotation_category failed: {exc}")
        return []


def _lookup_annotation_request_node_ids(pid_id: str) -> List[str]:
    """
    Fetch drawable Node IDs targeted by AnnotationRequest nodes for a PID.

    AnnotationRequest nodes are linked via (PID)-[:HAS_ANNOTATION]->(AnnotationRequest)
    and optionally (AnnotationRequest)-[:CONCERNS]->(Node).  Only Nodes that
    exist on the PID are returned; requests without a Node target are skipped.
    """
    if not pid_id or pid_id == "UNKNOWN":
        return []
    try:
        with _loader.driver.session(database=_loader.database) as sess:
            rows = sess.run(
                "MATCH (p:PID {pid_id: $pid})-[:HAS_ANNOTATION]->(ar:AnnotationRequest) "
                "OPTIONAL MATCH (ar)-[:CONCERNS]->(n:Node) "
                "WHERE n.id IS NOT NULL "
                "RETURN DISTINCT n.id AS node_id, "
                "       ar.anomaly_type AS anomaly_type, "
                "       ar.status AS status "
                "LIMIT 400",
                pid=pid_id,
            ).data()
        return list(dict.fromkeys(
            str(r.get("node_id") or "").strip()
            for r in rows if r.get("node_id")
        ))
    except Exception as exc:
        print(f"[SERVER] _lookup_annotation_request_node_ids failed: {exc}")
        return []


# ── Symbol dictionary integration ─────────────────────────────────────────────
# Maps graph Node.label / functional_label values to symbol_dictionary keys.
_LABEL_TO_DICT_KEY: Dict[str, str] = {
    "valve":              "valve",
    "tank":               "tank",
    "instrumentation":    "instrumentation",
    "general":            "general",
    "crossing":           "crossing",
    "arrow":              "arrow",
    "inlet/outlet":       "inlet/outlet",
    "inferred_check_valve": "inferred_check_valve",
    # functional_label overrides
    "pump":               "pump",
}


def _get_symbol_knowledge(label: str, functional_label: Optional[str] = None, skid_type: str = "CONDENSATE") -> Dict[str, str]:
    """
    Look up symbol_dictionary for a node and return human-readable fields:
      - Function:      what the symbol does
      - Why needed:    engineering justification for its presence
      - Placement:     where on a drawing it typically appears
      - Requires:      formatted list of required companion equipment
      - Safety:        safety criticality note
      - Failure mode:  consequence if missing or failed

    Returns an empty dict on any import/lookup failure so callers degrade gracefully.
    """
    try:
        from engine.domain_knowledge.symbol_dictionary import get_equipment_rules, UNIVERSAL_EQUIPMENT
    except ImportError:
        return {}

    # functional_label (e.g. "pump" on a tank node) takes precedence for rule lookup
    eff_label = _LABEL_TO_DICT_KEY.get(functional_label or "", "") \
                or _LABEL_TO_DICT_KEY.get(label or "", "")
    if not eff_label:
        return {}

    entry = UNIVERSAL_EQUIPMENT.get(eff_label, {})
    if not entry:
        return {}

    result: Dict[str, str] = {}

    desc = entry.get("description", "")
    if desc:
        result["Function"] = desc

    why = entry.get("why_needed", "")
    if why:
        result["Why needed"] = why

    placement = entry.get("typical_location", "")
    if placement:
        result["Placement"] = placement

    failure = entry.get("failure_mode", "")
    if failure:
        result["Failure mode"] = failure.replace("_", " ")

    if entry.get("safety_critical"):
        result["Safety critical"] = "Yes"

    # Format universal_requirements into a single readable string
    reqs = entry.get("universal_requirements", [])
    if reqs:
        req_parts: List[str] = []
        for r in reqs[:3]:  # cap at 3 to keep tooltip concise
            eq  = str(r.get("equipment") or r.get("equipment_category") or "")
            rsn = str(r.get("reason") or r.get("reason", ""))
            sev = str(r.get("severity") or "")
            hops = r.get("max_hops")
            part = eq.replace("_", " ")
            if rsn:
                part += f" ({rsn.replace('_', ' ')})"
            if sev:
                part += f" [{sev}]"
            if hops is not None:
                part += f" within {hops} pipe hops"
            if part:
                req_parts.append(part)
        if req_parts:
            result["Requires"] = "; ".join(req_parts)

    # Skid-specific additional context
    try:
        from engine.domain_knowledge.symbol_dictionary import SKID_CONTEXT
        skid_entry = SKID_CONTEXT.get(skid_type, {}).get(eff_label, {})
        downstream = skid_entry.get("required_downstream", [])
        if downstream:
            ds_parts = []
            for r in downstream[:2]:
                eq  = str(r.get("equipment", "")).replace("_", " ")
                rsn = str(r.get("reason", "")).replace("_", " ")
                if eq:
                    ds_parts.append(f"{eq} ({rsn})" if rsn else eq)
            if ds_parts:
                result[f"Requires downstream ({skid_type})"] = "; ".join(ds_parts)
    except Exception:
        pass

    return result



# Noise words stripped from question when building a compact query subject.
_REASON_NOISE: frozenset = frozenset({
    "show", "find", "list", "what", "which", "are", "is", "the", "a", "an",
    "me", "all", "of", "in", "for", "on", "with", "how", "many", "any",
    "has", "have", "been", "give", "get", "do", "does", "draw", "display",
    "tell", "about", "there", "those", "these", "both", "either", "also",
    "every", "please", "can", "could", "would", "their", "its", "where",
    "when", "just", "only", "and", "or", "not", "no", "if",
})


def _make_dynamic_reason(
    rec: Dict[str, Any],
    intent_type: str,
    question: str,
    q_lower: str,
) -> str:
    """
    Builds a concise, query-aware reason string for one highlighted node.
    Uses actual record fields (type, flow_state, connections, …) and keyword
    extraction from the original question so every tooltip is self-explaining.
    Downstream overrides (violation explanation, issue_reason, detail) in
    _build_node_details may supersede this for more specific cases.
    """
    # ── core type / flow fields ────────────────────────────────────────────
    ntype       = str(_first_scalar_value(
        rec,
        "type", "label", "node_type", "symbol_type",
        "equipment_type", "equipment_role", "valve_type", "vessel_type",
        "boundary_label", "drawing_label",
    ) or "").strip()
    flow_state  = str(_first_scalar_value(rec, "flow_state", "phase4_flow_state", "drawn_flow_state") or "").upper()
    flow_dir    = str(_first_scalar_value(
        rec,
        "flow_direction", "direction", "phase4_direction", "observed_direction", "evidence_direction",
    ) or "").upper()
    connections = _first_scalar_value(
        rec,
        "connections", "pipe_connections", "degree", "pipe_degree",
        "node_connectivity", "connectivity", "conn_count",
    )
    lps_id      = str(_first_scalar_value(
        rec,
        "lps_id", "logical_segment", "segment_id", "pipe_run", "pipe_line",
        "pipe_run_without_direction", "via_segment", "via_lps", "via_logical_segment",
        "from_lps", "to_lps", "logical_pipe_segment",
    ) or "").strip()
    rarity      = _first_scalar_value(rec, "rarity", "rarity_score")
    ntype_disp  = ntype.replace("_", " ").title() if ntype else ""

    # ── additional intent-specific fields ─────────────────────────────────
    confidence  = _first_scalar_value(rec, "confidence", "flow_confidence")
    cosine      = _first_scalar_value(rec, "cosine", "cosine_alignment")
    explanation = str(_first_scalar_value(rec, "explanation", "reason") or "").strip()
    rarity_lbl  = str(_first_scalar_value(rec, "rarity_label") or "").strip()
    pattern_type = str(_first_scalar_value(rec, "pattern_type", "anomaly_type") or "").strip()
    phase4_hint = str(_first_scalar_value(rec, "phase4_hint") or "").strip()
    hops        = _first_scalar_value(rec, "hops", "lps_hop_count")
    arrow_count = _first_scalar_value(rec, "arrow_count")
    arrow_id    = str(_first_scalar_value(rec, "arrow_id", "arrow") or "").strip()
    left_comp   = str(_first_scalar_value(rec, "left_component") or "").strip()
    right_comp  = str(_first_scalar_value(rec, "right_component") or "").strip()
    left_type   = str(_first_scalar_value(rec, "left_type") or "").strip()
    right_type  = str(_first_scalar_value(rec, "right_type") or "").strip()
    neighbour_t = str(_first_scalar_value(rec, "neighbour_types") or "").strip()
    eq_role     = str(_first_scalar_value(rec, "equipment_role") or "").strip()
    lps_conns   = _first_scalar_value(rec, "lps_connections")
    draw_loc    = str(_first_scalar_value(rec, "drawing_location") or "").strip()
    pipe_degree = _first_scalar_value(rec, "pipe_degree")
    ann_type    = str(_first_scalar_value(rec, "annotation_type", "category") or "").strip()

    # ── compact query subject (stop-word stripped) ─────────────────────────
    q_words = re.sub(r"[^a-z0-9 ]", " ", q_lower).split()
    q_subj  = " ".join(w for w in q_words if w not in _REASON_NOISE)
    if len(q_subj) > 50:
        q_subj = q_subj[:47] + "\u2026"

    def _cp() -> str:
        return f"{connections} pipe connection(s)" if connections is not None else ""

    def _fp() -> str:
        sm = {
            "SEEDED":     "confirmed on drawing",
            "PROPAGATED": "inferred from neighbour",
            "UNKNOWN":    "direction not determined",
        }
        dm = {"FORWARD": "downstream \u2192", "REVERSE": "\u2190 upstream"}
        parts: List[str] = []
        if flow_state in sm:
            parts.append(sm[flow_state])
        if flow_dir in dm:
            parts.append(dm[flow_dir])
        return ", ".join(parts)

    def _j(*parts) -> str:  # join non-empty strings with " — "
        return " \u2014 ".join(p for p in parts if p)

    # ══════════════════════════════════════════════════════════════════════
    # VALVE PLACEMENT
    # Available fields: valve_id, lps_id, flow_state, phase4_direction,
    #   left_component, left_type, right_component, right_type,
    #   lps_connections, confidence, deg/degree
    # ══════════════════════════════════════════════════════════════════════
    if intent_type == "valve_placement":
        v_kind = next(
            (k for k in ("isolation", "control", "check", "gate", "ball",
                         "butterfly", "needle", "relief", "safety", "globe")
             if k in q_lower), None
        )
        base = (ntype_disp or "Valve") + (f" ({v_kind} type)" if v_kind else "")
        # Neighbour context: what sits on each side of this valve?
        neighbour_parts: List[str] = []
        if left_type and right_type:
            lt = left_type.replace("_", " ").title()
            rt = right_type.replace("_", " ").title()
            neighbour_parts.append(f"{lt} \u2194 {rt}")
        elif left_type:
            neighbour_parts.append(f"left: {left_type.replace('_',' ').title()}")
        elif right_type:
            neighbour_parts.append(f"right: {right_type.replace('_',' ').title()}")
        seg_s = f"on {lps_id}" if lps_id else ""
        if not neighbour_parts:
            neighbour_parts.append(_cp() or "")
        return _j(base, *neighbour_parts, seg_s, _fp())

    # ══════════════════════════════════════════════════════════════════════
    # INSTRUMENT ATTACHMENT
    # Available fields: instrument_id, equipment_id, equipment_type,
    #   annotation_type, logical_pipe_segment, neighbour_types,
    #   drawn_flow_state, observed_direction, confidence
    # ══════════════════════════════════════════════════════════════════════
    if intent_type == "instrument_attachment":
        i_kind = next(
            (k for k in ("pressure", "temperature", "flow", "level", "control",
                         "transmitter", "gauge", "indicator", "switch", "analyzer")
             if k in q_lower), None
        )
        base = (ntype_disp or "Instrument") + (f" ({i_kind} type)" if i_kind else "")
        attach_parts: List[str] = []
        if lps_id:
            attach_parts.append(f"on segment {lps_id}")
        elif connections is not None:
            attach_parts.append(f"on {connections} pipe segment(s)")
        if neighbour_t:
            # neighbour_types is a list-like string: strip brackets
            nt_clean = neighbour_t.strip("[]").replace("'", "").replace('"', "")
            attach_parts.append(f"neighbours: {nt_clean[:40]}")
        if ann_type:
            ann_friendly = _ISSUE_DISPLAY_NAME.get(ann_type, ann_type.replace("_", " "))
            attach_parts.append(ann_friendly)
        return _j(base, *attach_parts)

    # ══════════════════════════════════════════════════════════════════════
    # ENGINEERING INVENTORY
    # Available fields: equipment_tag, equipment_type, structural_type,
    #   phase4_flow_state, lps_connections, location_on_drawing,
    #   valve_count, pump_count, instrument_count, tank_count, etc.
    # ══════════════════════════════════════════════════════════════════════
    if intent_type == "engineering_inventory":
        # Aggregate count records (whole-drawing inventory)
        count_fields = [
            ("valve_count", "valve"),
            ("pump_count", "pump"),
            ("instrument_count", "instrument"),
            ("inlet_outlet_count", "inlet/outlet"),
            ("crossing_count", "crossing"),
            ("connector_count", "connector"),
            ("arrow_node_count", "arrow"),
            ("general_count", "general component"),
            ("equipment_count", "equipment"),
            ("background_count", "background element"),
        ]
        for cf, cf_label in count_fields:
            cnt = _first_scalar_value(rec, cf)
            if cnt is not None:
                q_bit = f" — {q_subj}" if q_subj else ""
                return f"{cnt} {cf_label}(s) on this drawing{q_bit}"
        # Single-equipment records
        e_type = ntype_disp or "Equipment"
        if eq_role and eq_role.lower() not in (ntype.lower(), "equipment"):
            e_type = eq_role.replace("_", " ").title()
        seg_s = f"{lps_conns} pipe line(s)" if lps_conns is not None else _cp()
        fp = _fp()
        return _j(e_type, seg_s, fp or (f"inventory: {q_subj}" if q_subj else ""))

    # ══════════════════════════════════════════════════════════════════════
    # EXTERNAL INTERFACES
    # Available fields: interface_id, boundary_label, drawing_label,
    #   drawing_location, pipe_connectivity, node_connectivity,
    #   boundary_connectivity, degree, equipment_role,
    #   lps_id, flow_direction, flow_state,             ← from LPS join
    #   boundary_direction, boundary_confidence, direction_method  ← from phase3_boundary_semantics Evidence
    # ══════════════════════════════════════════════════════════════════════
    if intent_type == "external_interfaces":
        e_type = ntype_disp or "External interface"
        iface_kind = next(
            (k for k in ("inlet", "outlet", "feed", "return", "vent", "drain", "bypass")
             if k in q_lower), None
        )
        if not iface_kind and eq_role:
            eq_role_lower = eq_role.lower()
            if "inlet" in eq_role_lower or "input" in eq_role_lower:
                iface_kind = "inlet"
            elif "outlet" in eq_role_lower or "output" in eq_role_lower:
                iface_kind = "outlet"
        loc_s = draw_loc.upper() if draw_loc else ""
        loc_str = f"{loc_s} boundary" if loc_s else "drawing boundary"
        deg_s = f"{connections} connection(s)" if connections is not None else ""
        # Resolved flow direction: prefer boundary_direction from phase3_boundary_semantics
        # Evidence, fall back to LPS flow_direction if available
        b_dir  = str(_first_scalar_value(rec, "boundary_direction") or "").upper()
        b_conf = _first_scalar_value(rec, "boundary_confidence")
        b_meth = str(_first_scalar_value(rec, "direction_method") or "").strip()
        if not b_dir:
            b_dir = flow_dir
        dir_parts: List[str] = []
        if b_dir in ("FORWARD", "REVERSE"):
            dir_label = "downstream →" if b_dir == "FORWARD" else "← upstream"
            conf_s = f" ({float(b_conf):.0%})" if b_conf is not None else ""
            meth_s = f" via {b_meth}" if b_meth and b_meth != "bbox_fallback" else ""
            dir_parts.append(f"flow: {dir_label}{conf_s}{meth_s}")
        elif flow_state:
            fp = _fp()
            if fp:
                dir_parts.append(fp)
        return _j(e_type + (f" ({iface_kind})" if iface_kind else ""), loc_str,
                  *dir_parts, deg_s)

    # ══════════════════════════════════════════════════════════════════════
    # FLOW DIRECTION / DIRECTIONALITY DRAWN
    # Available fields: arrow_id, lps_id, cosine, confidence, direction,
    #   arrow_count, arrow_ids, covered_pipe_segments, equipment_a/b,
    #   equipment_a_type/b_type, has_conflicting_directions
    # ══════════════════════════════════════════════════════════════════════
    if intent_type in ("flow_direction", "directionality_drawn"):
        base = ntype_disp or "Flow direction arrow"
        extras: List[str] = []
        fp = _fp()
        if fp:
            extras.append(fp)
        if confidence is not None:
            try:
                extras.append(f"confidence {float(confidence):.0%}")
            except (ValueError, TypeError):
                pass
        if cosine is not None:
            try:
                extras.append(f"cosine {float(cosine):.2f}")
            except (ValueError, TypeError):
                pass
        if arrow_count is not None:
            extras.append(f"{arrow_count} arrow(s)")
        if lps_id:
            extras.append(f"segment {lps_id}")
        eq_a = str(_first_scalar_value(rec, "equipment_a") or "").strip()
        eq_b = str(_first_scalar_value(rec, "equipment_b") or "").strip()
        if eq_a and eq_b:
            extras.append(f"{eq_a} \u2192 {eq_b}")
        return _j(base, *extras) if extras else base

    # ══════════════════════════════════════════════════════════════════════
    # FLOW COVERAGE
    # Available fields: lps_id, flow_state, phase4_hint,
    #   missing_evidence_count, low_confidence_count, propagation_blocked
    # ══════════════════════════════════════════════════════════════════════
    if intent_type == "flow_coverage":
        if flow_state == "UNKNOWN":
            hint_map = {
                "direction_evidence_missing":      "no direction evidence found",
                "lps_low_confidence_evidence":     "low-confidence evidence only",
                "terminate_propagation":           "propagation blocked at junction",
            }
            hint_str = hint_map.get(phase4_hint, phase4_hint.replace("_", " ") if phase4_hint else "")
            seg_s = f" ({lps_id})" if lps_id else ""
            return _j(f"Pipe segment{seg_s}", "flow direction not resolved", hint_str)
        seg_s = f" ({lps_id})" if lps_id else ""
        return _j(f"Pipe segment{seg_s}", _fp())

    # ══════════════════════════════════════════════════════════════════════
    # LINE ATTRIBUTES
    # Available fields: lps_id, line_id, flow_state, phase4_hint,
    #   component_id, equipment_id, equipment_type, branch_count,
    #   avg_flow_confidence, isolated_line
    # ══════════════════════════════════════════════════════════════════════
    if intent_type == "line_attributes":
        hint_map = {
            "direction_evidence_missing":  "no direction evidence",
            "lps_low_confidence_evidence": "low confidence evidence",
            "terminate_propagation":       "propagation blocked",
        }
        comp_id = str(_first_scalar_value(rec, "component_id", "line_id") or "").strip()
        seg_s = f" {lps_id}" if lps_id else (f" {comp_id}" if comp_id else "")
        hint_str = hint_map.get(phase4_hint, phase4_hint.replace("_", " ") if phase4_hint else "")
        return _j(f"Pipe line{seg_s}", hint_str or _fp(), _cp())

    # ══════════════════════════════════════════════════════════════════════
    # SEGMENT / JUNCTION TOPOLOGY
    # Available fields: equipment_a, equipment_b, connected_lps,
    #   connected_lps_count, branch_junction_count, deg, adjacency_count
    # ══════════════════════════════════════════════════════════════════════
    if intent_type == "segment_junction_topology":
        eq_a = str(_first_scalar_value(rec, "equipment_a") or "").strip()
        eq_b = str(_first_scalar_value(rec, "equipment_b") or "").strip()
        clps = _first_scalar_value(rec, "connected_lps_count")
        base = ntype_disp or "Pipe crossing / junction point"
        cp = _cp()
        branch_parts: List[str] = []
        if clps is not None:
            branch_parts.append(f"{clps} connected segment(s)")
        elif cp:
            branch_parts.append(cp)
        if eq_a and eq_b:
            branch_parts.append(f"between {eq_a} \u2194 {eq_b}")
        return _j(base, *branch_parts)

    # ══════════════════════════════════════════════════════════════════════
    # CONNECTIVITY TOPOLOGY
    # Also used for GRAPH REACHABILITY (same cypher folder)
    # Available fields: equipment_tag, equipment_type, from_equipment,
    #   to_equipment, connected_lps, equipment_count, deg,
    #   component_size, cycle_count, isolated_equipment, hops
    # ══════════════════════════════════════════════════════════════════════
    if intent_type in ("connectivity_topology", "graph_reachability"):
        base = ntype_disp or "Connected node"
        quals: List[str] = []
        # Path / hop info
        if hops is not None:
            try:
                quals.append(f"{int(hops)} pipe hop(s)")
            except (ValueError, TypeError):
                quals.append(str(hops))
        elif pipe_degree is not None:
            quals.append(f"pipe degree: {pipe_degree}")
        # Directional context from question
        if "downstream" in q_lower:
            quals.append("downstream result")
        elif "upstream" in q_lower:
            quals.append("upstream result")
        elif "path" in q_lower or "between" in q_lower or "route" in q_lower:
            quals.append("path result")
        # Segment
        if lps_id:
            quals.append(f"via {lps_id}")
        elif _cp():
            quals.append(_cp())
        # Sub-graph statistics
        comp_size = _first_scalar_value(rec, "component_size")
        if comp_size is not None and intent_type == "graph_reachability":
            quals.append(f"component size: {comp_size}")
        iso = _first_scalar_value(rec, "isolated_equipment")
        if iso is not None and str(iso).strip() not in ("", "0", "False"):
            quals.append("isolated sub-network")
        if q_subj and not quals:
            quals.append(f"found by: \"{q_subj}\"")
        return _j(base, *quals)

    # ══════════════════════════════════════════════════════════════════════
    # REDUNDANCY PATTERNS
    # Available fields: pattern_type, rarity_label, rarity_score,
    #   pattern_frequency_count, pattern_rarity_count, cosine_alignment,
    #   evidence_source, confidence
    # ══════════════════════════════════════════════════════════════════════
    if intent_type == "redundancy_patterns":
        _RARITY_FRIENDLY = {
            "architecturally_rare":  "architecturally rare",
            "uncommon":              "uncommon",
            "common":                "common",
            "dominant":              "dominant",
            "typical":               "typical",
        }
        if rarity_lbl:
            friendly_rl = _RARITY_FRIENDLY.get(rarity_lbl, rarity_lbl.replace("_", " "))
            pat_str = ""
            if pattern_type:
                pat_str = f" ({_ISSUE_DISPLAY_NAME.get(pattern_type, pattern_type.replace('_',' '))})"
            rarity_s = ""
            if rarity is not None:
                try:
                    rarity_s = f" — score {float(rarity):.2f}"
                except (ValueError, TypeError):
                    pass
            return f"Pattern is {friendly_rl}{pat_str}{rarity_s}"
        if rarity is not None:
            try:
                r = float(rarity)
                label_guess = "rare" if r > 0.7 else ("uncommon" if r > 0.4 else "common")
                return f"Structural rarity {r:.2f} — {label_guess} motif in this drawing"
            except (ValueError, TypeError):
                pass
        if pattern_type:
            return _j("Structural pattern", _ISSUE_DISPLAY_NAME.get(pattern_type, pattern_type.replace("_", " ")))
        return "Rare or structurally dominant symbol in this PID"

    # ══════════════════════════════════════════════════════════════════════
    # ANNOTATION REQUESTS
    # Available fields: annotation_id, annotation_type, category,
    #   open_request_count, high_severity_count, esv_count, kav_count
    # ══════════════════════════════════════════════════════════════════════
    if intent_type == "annotation_requests":
        if ann_type:
            ann_friendly = _ISSUE_DISPLAY_NAME.get(ann_type, ann_type.replace("_", " "))
            return f"Open annotation request: {ann_friendly} — pending engineer review"
        open_ct = _first_scalar_value(rec, "open_request_count")
        if open_ct is not None:
            return f"{open_ct} open annotation request(s) — pending engineer review"
        return "Has an open annotation request pending engineer review"

    # ══════════════════════════════════════════════════════════════════════
    # CROSS DOMAIN (valves + flow + LPS + annotations combined)
    # Available fields: valve_id, lps_id, flow_state, annotation_type,
    #   severity, instrument_id, confidence, dangling, node_label
    # ══════════════════════════════════════════════════════════════════════
    if intent_type == "cross_domain":
        base = ntype_disp or "Symbol"
        quals: List[str] = []
        fp = _fp()
        if fp:
            quals.append(fp)
        if ann_type:
            quals.append(_ISSUE_DISPLAY_NAME.get(ann_type, ann_type.replace("_", " ")))
        if lps_id:
            quals.append(f"on {lps_id}")
        elif _cp():
            quals.append(_cp())
        sev = str(_first_scalar_value(rec, "severity") or "").strip()
        if sev:
            quals.append(f"severity: {sev}")
        if not quals and q_subj:
            quals.append(f"cross-domain: {q_subj}")
        return _j(base, *quals)

    # ══════════════════════════════════════════════════════════════════════
    # DRAWING CONSISTENCY (also used for ISOLATION REACHABILITY — same
    # cypher folder; isolation records have pattern_type from Annotation)
    # Available fields: element_id/equipment_id, issue_type/pattern_type,
    #   branch_count, cycle_count, dead_end_count, manifold_count,
    #   orphan_count, collision_count, occurrences, flow_state
    # ══════════════════════════════════════════════════════════════════════
    if intent_type in ("drawing_consistency", "isolation_reachability"):
        issue_t = str(_first_scalar_value(rec, "type", "issue_type", "anomaly_type", "pattern_type") or "").strip()
        friendly = _ISSUE_DISPLAY_NAME.get(issue_t)
        reason_t = _ISSUE_REASON_MAP.get(issue_t, "")
        if friendly:
            return _j(friendly, reason_t)
        eq_t = str(_first_scalar_value(rec, "equipment_type") or "").strip()
        base = (eq_t.replace("_", " ").title() if eq_t else ntype_disp) or "Symbol"
        occ = _first_scalar_value(rec, "occurrences")
        occ_s = f"{occ} occurrence(s)" if occ is not None else ""
        return _j(base, "flagged by quality check", occ_s, f"\"{q_subj}\"" if q_subj else "")

    # ══════════════════════════════════════════════════════════════════════
    # ENGINEERING CORRECTNESS / VIOLATIONS
    # Available fields: equipment_id, equipment_type, equipment_role,
    #   pump_id, rule_id/rule_name, explanation, review_status,
    #   pipe_degree, actual_degree, check_valves, has_instrument,
    #   pump_without_check_valve, pump_without_isolation,
    #   flow_state, direction, confidence, reachable_valves
    # ══════════════════════════════════════════════════════════════════════
    if intent_type in ("engineering_correctness", "engineering_violations"):
        role  = str(_first_scalar_value(rec, "equipment_role", "vessel_type") or "").strip()
        rule  = str(_first_scalar_value(rec, "rule_id", "rule_name", "rule_type") or "").strip()
        base  = role.replace("_", " ").title() if role else (ntype_disp or "Equipment")
        # Use explanation if available (richest text)
        if explanation:
            return _j(base, explanation[:100])
        rule_friendly = _ISSUE_DISPLAY_NAME.get(rule, rule.replace("_", " ")) if rule else ""
        rv = _first_scalar_value(rec, "reachable_valves")
        rv_s = f"{rv} reachable valve(s)" if rv is not None else ""
        has_instr = _first_scalar_value(rec, "has_instrument")
        instr_s = ("instrumented" if str(has_instr).lower() in ("true", "1", "yes")
                   else "no instrument" if has_instr is not None else "")
        pd_val = str(_first_scalar_value(rec, "pipe_degree", "actual_degree") or "").strip()
        pd_s = f"pipe degree: {pd_val}" if pd_val else ""
        sev = str(_first_scalar_value(rec, "severity") or "").strip()
        sev_s = f"{sev} severity" if sev else ""
        qual_parts = [p for p in [rule_friendly or "engineering rule check", rv_s, pd_s, instr_s, sev_s] if p]
        return _j(base, *qual_parts[:3])  # cap at 3 qualifiers

    # ══════════════════════════════════════════════════════════════════════
    # Generic fallback
    # ══════════════════════════════════════════════════════════════════════
    fp = _fp()
    cp = _cp()
    parts: List[str] = [ntype_disp] if ntype_disp else []
    if fp:
        parts.append(fp)
    elif cp:
        parts.append(cp)
    if q_subj:
        parts.append(f"\"{q_subj}\"")
    return " \u2014 ".join(parts) if parts else \
        f"matched by {intent_type.replace('_', ' ').lower()} query"


def _build_node_details(
    records: List[Dict[str, Any]],
    intent_type: str,
    question: str,
    pid_id: str = "UNKNOWN",
    anchor_node: str = "",
) -> Dict[str, Any]:
    by_id:    Dict[str, Any] = {}
    by_label: Dict[str, Any] = {}
    base_reason = _INTENT_REASON.get(intent_type, f"Matched by: {intent_type}")
    q_lower = (question or "").lower()
    node_universe = _pid_node_universe(pid_id)

    # Resolve the skid_type for the active PID so symbol knowledge can apply
    # skid-specific requirements (e.g. CONDENSATE pump rules).
    # Uses the module-level cache -- at most one Neo4j round trip per PID.
    _skid_type = _get_skid_type(pid_id)

    # Intents for which symbol knowledge tooltips are useful — not for quality/violation intents
    # where the annotation explanation already provides full context.
    _SYMBOL_KNOWLEDGE_INTENTS = {
        "valve_placement", "instrument_attachment", "engineering_inventory",
        "external_interfaces", "connectivity_topology", "flow_direction",
        "flow_coverage", "directionality_drawn", "line_attributes",
        "cross_domain",
    }

    # For directional connectivity queries, give a meaningful per-node reason
    if intent_type == "connectivity_topology" and anchor_node:
        q_lower = question.lower()
        if "downstream" in q_lower:
            base_reason = f"Downstream of {anchor_node} — found via flow path"
        elif "upstream" in q_lower:
            base_reason = f"Upstream of {anchor_node} — found via flow path"

    for rec in records:
        nid = _first_node_id_from_record(rec, node_universe)

        details: Dict[str, str] = {}
        for field, label in _DETAIL_FIELDS.items():
            v = _first_scalar_value(rec, field)
            if v is not None:
                raw = str(v)
                display = _FIELD_VALUE_DISPLAY.get(field, {}).get(raw.upper(), raw) \
                    if field in _FIELD_VALUE_DISPLAY else raw
                details[label] = display

        if nid:
            # Start with a query-aware per-record reason; specific overrides below
            # (issue_reason, violation explanation, detail) may supersede it.
            reason = _make_dynamic_reason(rec, intent_type, question, q_lower)
            # Violation records: use actual explanation from Annotation
            explanation = _first_scalar_value(rec, "explanation")
            rule_name = _first_scalar_value(rec, "rule_name")
            rule_id = _first_scalar_value(rec, "rule_id")
            if explanation and (rule_name or rule_id):
                rule = str(rule_name or rule_id or "")
                friendly_rule = _ISSUE_DISPLAY_NAME.get(rule, rule) or rule
                reason = str(explanation)
                details["Violation"] = str(friendly_rule)
                sev = str(_first_scalar_value(rec, "severity") or "")
                if sev:
                    details["Severity"] = sev
                req = _first_scalar_value(rec, "required_equipment")
                if req:
                    details["Required"] = str(req).replace("_", " ")
                review = _first_scalar_value(rec, "review_status")
                if review:
                    details["Review"] = str(review)
                by_id[nid] = {
                    "reason":   reason,
                    "details":  details,
                    "severity": sev,
                }
            else:
                anomaly_type = _first_scalar_value(rec, "anomaly_type")
                issue_t      = _first_scalar_value(rec, "issue_type", "type")
                detail       = _first_scalar_value(rec, "detail")
                flow_state   = str(_first_scalar_value(rec, "flow_state") or "")
                connections  = _first_scalar_value(rec, "connections")
                # issue_str: non-empty string from issue_type/type fields that maps
                # to a known annotation issue (e.g. "orphan_node", "missing_check_valve").
                # We distinguish these from label values like "valve" which are NOT in
                # _ISSUE_REASON_MAP.
                issue_str      = str(issue_t or "").strip()
                issue_reason   = _ISSUE_REASON_MAP.get(str(anomaly_type or "").strip()) \
                                 or _ISSUE_REASON_MAP.get(issue_str)
                if issue_reason:
                    reason = issue_reason
                    # Relabel "Symbol type: issue_name" → "Issue: friendly display name"
                    sym_val = str(details.get("Symbol type") or "").strip()
                    if sym_val and sym_val in _ISSUE_REASON_MAP:
                        details["Issue"] = _ISSUE_DISPLAY_NAME.get(sym_val) or sym_val
                        del details["Symbol type"]
                elif detail:
                    reason = str(detail)[:120]
                # Note: flow_state / connections fallbacks removed — _make_dynamic_reason
                # handles both more accurately per intent type.
                # Enrich with symbol dictionary knowledge for supported intents
                if intent_type in _SYMBOL_KNOWLEDGE_INTENTS:
                    raw_lbl = str(_first_scalar_value(rec, "label", "type") or "").strip()
                    raw_fn  = str(_first_scalar_value(rec, "functional_label") or "").strip()
                    sym_info = _get_symbol_knowledge(raw_lbl, raw_fn or None, _skid_type)
                    for k, v in sym_info.items():
                        if k not in details:   # don't overwrite fields from the record itself
                            details[k] = v
                by_id[nid] = {"reason": reason, "details": details}
        else:
            lbl = None
            for f in _LABEL_FIELDS:
                raw_lbl = _first_scalar_value(rec, f)
                v = str(raw_lbl or "").lower().strip()
                if _LABEL_MAP.get(v):
                    lbl = _LABEL_MAP[v]
                    break
            if not lbl:
                # Generic fallback for aliases like equipment_type, boundary_label, etc.
                for full, base, raw in _iter_record_entries(rec):
                    if not (full.endswith("_type") or base.endswith("_type") or full.endswith("_label") or base.endswith("_label")):
                        continue
                    if raw is None or isinstance(raw, (list, dict)):
                        continue
                    v = str(raw).lower().strip()
                    if _LABEL_MAP.get(v):
                        lbl = _LABEL_MAP[v]
                        break
            if lbl:
                count = (
                    _first_scalar_value(rec, "total")
                    or _first_scalar_value(rec, "count")
                    or _first_scalar_value(rec, "occurrences")
                    or ""
                )
                # Build a query-aware label reason embedding the query subject
                _q_words  = re.sub(r"[^a-z0-9 ]", " ", q_lower).split()
                _q_subj   = " ".join(w for w in _q_words if w not in _REASON_NOISE)
                _q_subj   = _q_subj[:50] + ("\u2026" if len(_q_subj) > 50 else "")
                reason = base_reason
                if count and _q_subj:
                    reason = f"{count} {lbl}(s) \u2014 {_q_subj}"
                elif count:
                    reason = f"{count} {lbl}(s) \u2014 {base_reason}"
                elif _q_subj:
                    reason = f"{lbl.title()} \u2014 {_q_subj}"
                # Enrich by_label entries with symbol dictionary function description
                if intent_type in _SYMBOL_KNOWLEDGE_INTENTS:
                    sym_info = _get_symbol_knowledge(lbl, None, _skid_type)
                    for k, v in sym_info.items():
                        if k not in details:
                            details[k] = v
                by_label[lbl] = {"reason": reason, "details": details}

    if not by_id and not by_label:
        for lbl in _INTENT_LBLS.get(intent_type, []):
            by_label[lbl] = {"reason": base_reason, "details": {}}

    # For downstream/upstream queries: add the source node explicitly so its
    # tooltip shows "Query source" instead of a generic fallback.
    if intent_type == "connectivity_topology" and anchor_node and anchor_node not in by_id:
        q_lower = question.lower()
        if "downstream" in q_lower:
            src_reason = f"Flow source — you asked about what is downstream of {anchor_node}"
        elif "upstream" in q_lower:
            src_reason = f"Flow source — you asked about what is upstream of {anchor_node}"
        else:
            src_reason = f"Query source — you asked about {anchor_node}"
        by_id[anchor_node] = {"reason": src_reason, "details": {}}

    # Quality / consistency / isolation intents — enrich per-node context
    # isolation_reachability is included so aggregate component queries still
    # highlight the actual orphaned nodes with their specific issue reasons.
    quality_intents = {
        "drawing_consistency", "engineering_correctness",
        "annotation_requests", "engineering_violations",
        "isolation_reachability",
    }
    if intent_type in quality_intents and not by_id:
        # annotation_requests: AnnotationRequest targets are separate from
        # Annotation nodes — query via the dedicated helper, not issue lookup.
        if intent_type == "annotation_requests":
            ar_ids = _lookup_annotation_request_node_ids(pid_id)
            for nid in ar_ids:
                by_id[nid] = {
                    "reason":  "Annotation request pending review",
                    "details": {"Status": "OPEN"},
                }
        else:
            issue_types: List[str] = []
            for r in records:
                issue = _first_scalar_value(r, "issue_type", "type", "rule_name", "rule_id")
                if not issue:
                    continue
                issue_str = str(issue).strip()
                if issue_str and issue_str not in issue_types:
                    issue_types.append(issue_str)

            # Direction-observation aggregates are informational; for quality summaries,
            # fall back to defect/topology issues so engineers still see actionable nodes.
            if issue_types and all(t in {"direction_observation", "direction_frequency_summary"} for t in issue_types):
                issue_types = []

            if not issue_types:
                # Per-intent defaults when no issue types found in records
                if intent_type == "isolation_reachability":
                    issue_types = ["orphan_node"]
                elif intent_type == "engineering_correctness":
                    issue_types = list(_ENGINEERING_VIOLATIONS)
                else:
                    # drawing_consistency / engineering_violations: full defect sweep
                    issue_types = list(
                        _DEFECT_ISSUES | _PIPE_SEGMENT_DEFECTS | _TOPOLOGY_ISSUES | _PIPE_SEGMENT_INFO
                    )

            explicitly_topology = bool(
                issue_types and any(
                    t in (_TOPOLOGY_ISSUES | _PIPE_SEGMENT_DEFECTS | _PIPE_SEGMENT_INFO)
                    for t in issue_types if t
                )
            )

            flagged_rows = _lookup_node_ids_for_issues(
                issue_types, pid_id, allow_topology=explicitly_topology
            )
            for row in flagged_rows:
                nid = row.get("node_id", "")
                if not nid:
                    continue

                issue       = row.get("issue_type", "")
                is_violation= issue in _ENGINEERING_VIOLATIONS
                is_topology = issue in _TOPOLOGY_ISSUES
                is_pipe_seg = issue in (_PIPE_SEGMENT_DEFECTS | _PIPE_SEGMENT_INFO)

                if is_violation:
                    sev = row.get("severity") or _VIOLATION_SEVERITY.get(issue, "MEDIUM")
                    raw_category = f"safety-{sev.lower()}"
                    reason = row.get("explanation") or _ISSUE_REASON_MAP.get(issue, issue)
                elif is_topology:
                    raw_category = "topology"
                    reason = _ISSUE_REASON_MAP.get(issue, f"Topology: {issue}")
                elif is_pipe_seg:
                    raw_category = "pipe-run defect"
                    reason = _ISSUE_REASON_MAP.get(issue, f"Pipe issue: {issue}")
                else:
                    raw_category = "defect"
                    reason = _ISSUE_REASON_MAP.get(
                        issue, f"Drawing issue: {_ISSUE_DISPLAY_NAME.get(issue, issue)}"
                    )

                symbol_label = row.get("label", "")
                friendly_label = {
                    "connector":       "pipe connector",
                    "general":         "general symbol",
                    "inferred_check_valve": "inferred check valve",
                    "valve":           "valve",
                    "tank":            "tank/vessel",
                    "instrumentation": "instrument",
                    "inlet/outlet":    "external interface",
                    "arrow":           "flow arrow",
                }.get(symbol_label, symbol_label)

                # Dict[str, Any] — values are str in the base case, but the violation
                # branch adds sev which Pylance infers as str | None from row.get(),
                # and _ISSUE_DISPLAY_NAME.get() is conservatively typed str | None in
                # strict mode even when a str default is supplied.
                node_details: Dict[str, Any] = {
                    "Symbol": friendly_label,
                    "Issue":  _ISSUE_DISPLAY_NAME.get(issue) or issue,
                    "Status": _CATEGORY_DISPLAY.get(raw_category) or raw_category,
                }
                # Phase 3.5: add severity and skid_type to tooltip
                if is_violation:
                    sev: str = row.get("severity") or _VIOLATION_SEVERITY.get(issue, "MEDIUM") or "MEDIUM"
                    node_details["Severity"] = sev
                    if row.get("skid_type"):
                        node_details["Skid type"] = str(row["skid_type"])

                by_id[nid] = {
                    "reason":   reason,
                    "details":  node_details,
                    "severity": row.get("severity") if is_violation else None,
                }

    # Rarity / redundancy queries often return annotation IDs and score buckets
    # without explicit node IDs. Resolve those annotations back to drawable nodes.
    if intent_type == "redundancy_patterns" and not by_id:
        ann_types: List[str] = []
        pattern_types: List[str] = []
        for r in records:
            ann_t = _first_scalar_value(r, "type")
            pat_t = _first_scalar_value(r, "pattern_type")
            if ann_t:
                ann_t_str = str(ann_t).strip()
                if ann_t_str and ann_t_str not in ann_types:
                    ann_types.append(ann_t_str)
            if pat_t:
                pat_t_str = str(pat_t).strip()
                if pat_t_str and pat_t_str != "__summary__" and pat_t_str not in pattern_types:
                    pattern_types.append(pat_t_str)

        default_ann_types = ["structural_pattern_rarity", "rare_motif_local"]
        if not ann_types:
            ann_types = list(default_ann_types)

        rarity_rows = _lookup_node_ids_for_rarity(pid_id, ann_types=ann_types, pattern_types=pattern_types)
        if not rarity_rows:
            rarity_rows = _lookup_node_ids_for_rarity(
                pid_id,
                ann_types=default_ann_types,
                pattern_types=[],
            )
        for row in rarity_rows:
            nid = str(row.get("node_id") or "").strip()
            if not nid:
                continue
            issue = str(row.get("issue_type") or "structural_pattern_rarity")
            reason = _ISSUE_REASON_MAP.get(issue, "Rare or dominant structural pattern")
            rarity_details: Dict[str, Any] = {
                "Issue": _ISSUE_DISPLAY_NAME.get(issue) or issue,
            }
            rarity_label = row.get("rarity_label")
            if rarity_label:
                rarity_details["Rarity"] = str(rarity_label)
            rarity_score = row.get("rarity_score")
            if rarity_score is not None:
                rarity_details["Rarity score"] = str(rarity_score)
            rarity_sev = row.get("severity")
            if rarity_sev:
                rarity_details["Severity"] = str(rarity_sev)
            by_id[nid] = {
                "reason": reason,
                "details": rarity_details,
                "severity": str(rarity_sev) if rarity_sev else None,
            }

    if intent_type == "engineering_inventory" and not by_id and "pump" in q_lower:
        pump_ids = _node_ids_by_functional_label(pid_id, "pump")
        for nid in pump_ids:
            by_id[nid] = {
                "reason": "Pump role — included in equipment inventory",
                "details": {"Role": "pump"},
            }

    if intent_type == "cross_domain" and not by_id and (
        ("quality" in q_lower and "annotation" in q_lower)
        or ("flagged" in q_lower and "review" in q_lower)
    ):
        issue_types = list(
            _DEFECT_ISSUES | _PIPE_SEGMENT_DEFECTS | _TOPOLOGY_ISSUES | _PIPE_SEGMENT_INFO
        )
        flagged_rows = _lookup_node_ids_for_issues(issue_types, pid_id, allow_topology=True)
        for row in flagged_rows:
            nid = str(row.get("node_id") or "").strip()
            if not nid:
                continue
            issue = str(row.get("issue_type") or "")
            by_id[nid] = {
                "reason": _ISSUE_REASON_MAP.get(issue, "Annotated quality finding"),
                "details": {
                    "Issue": _ISSUE_DISPLAY_NAME.get(issue) or issue,
                    "Status": "Quality annotation",
                },
            }

    if intent_type == "cross_domain" and not by_id and (
        "esv" in q_lower or "equipment semantics" in q_lower
    ):
        esv_ids = _lookup_node_ids_by_annotation_category(pid_id, "ESV")
        for nid in esv_ids:
            by_id[nid] = {
                "reason": "Equipment semantics annotation (ESV)",
                "details": {"Category": "ESV"},
            }
        if not esv_ids:
            for lbl in ["tank", "valve", "instrumentation", "inlet/outlet"]:
                by_label[lbl] = {
                    "reason": "Equipment semantics summary — highlighted by symbol family",
                    "details": {"Category": "ESV"},
                }

    # ── Pipe-intent LPS context ───────────────────────────────────────────────
    # For pipe-trace queries the tooltip in drawPipes looks up ctx.by_id[trace.lps_id].
    # Populate by_id with LPS ids so each pipe trace gets intent-specific hover text.
    _PIPE_CONTEXT_INTENTS = {
        "flow_coverage", "line_attributes", "flow_direction", "directionality_drawn",
        "connectivity_topology", "segment_junction_topology", "graph_reachability",
    }
    if intent_type in _PIPE_CONTEXT_INTENTS:
        for rec in records:
            for field in _LPS_ID_FIELDS:
                for raw in _iter_field_values(rec, field):
                    if not isinstance(raw, str):
                        continue
                    lps = raw.strip()
                    if not lps or "__" not in lps or lps in by_id:
                        continue
                    lps_reason = _make_dynamic_reason(rec, intent_type, question, q_lower)
                    lps_detail: Dict[str, str] = {}
                    for f2, label2 in _DETAIL_FIELDS.items():
                        v = _first_scalar_value(rec, f2)
                        if v is not None:
                            raw2 = str(v)
                            disp = _FIELD_VALUE_DISPLAY.get(f2, {}).get(raw2.upper(), raw2) \
                                if f2 in _FIELD_VALUE_DISPLAY else raw2
                            lps_detail[label2] = disp
                    by_id[lps] = {"reason": lps_reason, "details": lps_detail}

    return {"by_id": by_id, "by_label": by_label, "query": question}


def _fetch_lps_traces(pid_id: str, lps_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Fetch LogicalPipeSegment trace_nodes for pipe highlighting.

    If lps_ids is given, return only those segments; otherwise return all LPS for
    the PID (used for flow-coverage / flow-direction aggregate queries where we want
    to paint every pipe line on the canvas colour-coded by flow_state).

    Returns list of dicts:
        { lps_id, trace_nodes, flow_state, flow_direction, flow_confidence }
    """
    try:
        with _loader.driver.session(database=_loader.database) as sess:
            if lps_ids:
                rows = sess.run(
                    "UNWIND $ids AS lid "
                    "MATCH (lps:LogicalPipeSegment {id: lid, pid_id: $pid}) "
                    "RETURN lps.id AS lps_id, lps.trace_nodes AS trace_nodes, "
                    "       lps.flow_state AS flow_state, "
                    "       lps.flow_direction AS flow_direction, "
                    "       lps.flow_confidence AS flow_confidence",
                    ids=lps_ids, pid=pid_id,
                ).data()
            else:
                rows = sess.run(
                    "MATCH (lps:LogicalPipeSegment {pid_id: $pid}) "
                    "WHERE lps.trace_nodes IS NOT NULL "
                    "RETURN lps.id AS lps_id, lps.trace_nodes AS trace_nodes, "
                    "       lps.flow_state AS flow_state, "
                    "       lps.flow_direction AS flow_direction, "
                    "       lps.flow_confidence AS flow_confidence",
                    pid=pid_id,
                ).data()
        return [
            {
                "lps_id":          r["lps_id"],
                "trace_nodes":     r["trace_nodes"] or [],
                "flow_state":      r.get("flow_state") or "UNKNOWN",
                "flow_direction":  r.get("flow_direction"),
                "flow_confidence": float(r["flow_confidence"]) if r.get("flow_confidence") is not None else None,
            }
            for r in rows
            if r.get("trace_nodes")
        ]
    except Exception as exc:
        print(f"[SERVER] _fetch_lps_traces failed: {exc}")
        return []


def _fetch_pipe_neighbors(node_ids: List[str], pid_id: str) -> Dict[str, List[str]]:
    """
    For each node_id, fetch its direct PIPE neighbors (1 hop).
    Returns {node_id: [neighbor_id, ...]} for context highlighting.
    """
    if not node_ids:
        return {}
    try:
        with _loader.driver.session(database=_loader.database) as sess:
            rows = sess.run(
                "UNWIND $ids AS nid "
                "MATCH (n:Node {id: nid, pid_id: $pid})-[:PIPE]-(m:Node) "
                "RETURN n.id AS source, collect(DISTINCT m.id) AS neighbors",
                ids=node_ids, pid=pid_id,
            ).data()
            return {r["source"]: r["neighbors"] for r in rows}
    except Exception as exc:
        print(f"[SERVER] _fetch_pipe_neighbors failed: {exc}")
        return {}


def _fetch_junction_traces_for_nodes(node_ids: List[str], pid_id: str) -> List[Dict[str, Any]]:
    """
    For each junction centre node ID, fetch the JOINS_AT.trace_nodes lists that
    pass through that node.  Returns trace objects compatible with _fetch_lps_traces
    output so the client can render them as coloured pipe polylines.

    Each JOINS_AT relation has a trace_nodes list: [connector_before, junction_centre,
    connector_after].  These 3 nodes form a short path that visually marks where two
    PipeSegments meet on the drawing.
    """
    if not node_ids or not pid_id or pid_id == "UNKNOWN":
        return []
    try:
        with _loader.driver.session(database=_loader.database) as sess:
            rows = sess.run(
                "UNWIND $ids AS nid "
                "MATCH (ps1:PipeSegment {pid_id: $pid})-[j:JOINS_AT]->(ps2:PipeSegment) "
                "WHERE j.trace_nodes[1] = nid "
                "RETURN nid AS junction_id, j.trace_nodes AS trace_nodes, "
                "       j.kind AS kind, ps1.id AS seg_a, ps2.id AS seg_b "
                "LIMIT 400",
                ids=node_ids, pid=pid_id,
            ).data()
        traces: List[Dict[str, Any]] = []
        seen: set = set()
        for r in rows:
            tn = r.get("trace_nodes") or []
            if not tn or len(tn) < 2:
                continue
            key = tuple(tn)
            if key in seen:
                continue
            seen.add(key)
            traces.append({
                "lps_id":         f"junction_{r['junction_id']}_{r.get('seg_a','')}",
                "trace_nodes":    tn,
                "flow_state":     "UNKNOWN",   # junctions have no resolved flow direction
                "flow_direction":  None,
                "flow_confidence": None,
            })
        return traces
    except Exception as exc:
        print(f"[SERVER] _fetch_junction_traces_for_nodes failed: {exc}")
        return []


def _fetch_dead_segment_traces(pid_id: str) -> List[Dict[str, Any]]:
    """
    Fetch LPS traces that cover PipeSegments annotated as dead-end or
    unmapped stubs so engineers can see the exact pipe runs on the canvas.

    Returns:
        dead_end  — LPS traces for dead-end pipe stubs (one equipment endpoint,
                    flow_state preserved so SEEDED/PROPAGATED states show correctly)
        orphan_ps — JOINS_AT trace_nodes for pipe_segment_no_logical_mapping stubs
                    (these have no LPS; the trace is reconstructed from node coords)
    """
    if not pid_id or pid_id == "UNKNOWN":
        return []
    try:
        with _loader.driver.session(database=_loader.database) as sess:
            # Dead-end PipeSegments: find overlapping LPS via [:COVERS]
            rows = sess.run(
                "MATCH (ann:Annotation {pid_id: $pid, type: 'dead_end_pipe_segment'})"
                "-[:ANNOTATES]->(ps:PipeSegment) "
                "OPTIONAL MATCH (lps:LogicalPipeSegment)-[:COVERS]->(ps) "
                "WHERE lps.trace_nodes IS NOT NULL "
                "RETURN lps.id AS lps_id, lps.trace_nodes AS trace_nodes, "
                "       lps.flow_state AS flow_state, "
                "       lps.flow_direction AS flow_direction, "
                "       lps.flow_confidence AS flow_confidence "
                "LIMIT 200",
                pid=pid_id,
            ).data()
        traces = [
            {
                "lps_id":         r["lps_id"],
                "trace_nodes":    r["trace_nodes"] or [],
                "flow_state":     r.get("flow_state") or "UNKNOWN",
                "flow_direction":  r.get("flow_direction"),
                "flow_confidence": float(r["flow_confidence"]) if r.get("flow_confidence") is not None else None,
            }
            for r in rows
            if r.get("lps_id") and r.get("trace_nodes")
        ]
        return list({t["lps_id"]: t for t in traces}.values())  # deduplicate by lps_id
    except Exception as exc:
        print(f"[SERVER] _fetch_dead_segment_traces failed: {exc}")
        return []


def _highlight(
    records,
    intent_type,
    pid_id: str = "UNKNOWN",
    anchor_node: str = "",
    question: str = "",
):
    q_lower = (question or "").lower()
    node_universe = _pid_node_universe(pid_id)
    ids, lps_ids, path_lists = _extract_ids_and_paths(records, node_universe)

    # ── 0. Connectivity path (upstream/downstream/path) → pipe traces + endpoints
    # When records contain BOTH node ids (far endpoints) and LPS ids (the route),
    # show the pipe as a coloured trace and draw boxes at the destination nodes.
    if intent_type == "connectivity_topology" and lps_ids:
        traces = _fetch_lps_traces(pid_id, lps_ids)
        if traces:
            # Include the queried node (anchor) as an endpoint box alongside results
            ep = list(dict.fromkeys(filter(None, ids + ([anchor_node] if anchor_node else []))))
            return {
                "mode":           "pipes",
                "node_ids":       [],
                "labels":         [],
                "pipe_traces":    traces,
                "endpoint_nodes": ep,
            }

    # ── 0b. Connectivity path fallback from explicit path-node lists ─────────
    if intent_type == "connectivity_topology" and path_lists:
        traces = [
            {
                "lps_id": f"path_{i+1}",
                "trace_nodes": path,
                "flow_state": "UNKNOWN",
                "flow_direction": None,
                "flow_confidence": None,
            }
            for i, path in enumerate(path_lists)
            if len(path) >= 2
        ]
        if traces:
            ep = list(dict.fromkeys(filter(None, ids + ([anchor_node] if anchor_node else []))))
            return {
                "mode":           "pipes",
                "node_ids":       [],
                "labels":         [],
                "pipe_traces":    traces,
                "endpoint_nodes": ep,
            }

    # ── 1. Pipe-trace for aggregate flow/line queries (no individual node IDs) ─
    if intent_type in _PIPE_INTENTS and not ids:
        traces = _fetch_lps_traces(pid_id, lps_ids if lps_ids else None)
        if traces:
            # Apply per-LPS overrides when query returned specific flow states
            state_override: Dict[str, str] = {}
            dir_override: Dict[str, Optional[str]] = {}
            for r in records:
                for f in _LPS_ID_FIELDS:
                    lid = str(r.get(f, "")) if r.get(f) else ""
                    if lid and "__" in lid:
                        if r.get("flow_state"):
                            state_override[lid] = str(r["flow_state"])
                        if r.get("flow_direction"):
                            dir_override[lid] = str(r["flow_direction"])
            for t in traces:
                if t["lps_id"] in state_override:
                    t["flow_state"] = state_override[t["lps_id"]]
                if t["lps_id"] in dir_override:
                    t["flow_direction"] = dir_override[t["lps_id"]]
            return {"mode": "pipes", "node_ids": [], "labels": [], "pipe_traces": traces}

    # ── 2. Pipe-trace + node boxes for list flow queries ─────────────────────
    # e.g. "show valves with SEEDED flow" → trace the pipe AND box the valve nodes
    if intent_type in _PIPE_INTENTS and ids and lps_ids:
        traces = _fetch_lps_traces(pid_id, lps_ids)
        if traces:
            return {
                "mode":           "pipes",
                "node_ids":       [],
                "labels":         [],
                "pipe_traces":    traces,
                "endpoint_nodes": ids,
            }

    # ── 2b. Junction-topology: server-side JOINS_AT trace fetch ─────────────
    # When records return junction centre node IDs (junction_symbol field), look
    # up the full JOINS_AT.trace_nodes in Neo4j so the client renders the short
    # pipe path through each junction instead of just drawing plain boxes.
    if intent_type == "segment_junction_topology" and ids:
        j_traces = _fetch_junction_traces_for_nodes(ids, pid_id)
        if j_traces:
            return {
                "mode":           "pipes",
                "node_ids":       [],
                "labels":         [],
                "pipe_traces":    j_traces,
                "endpoint_nodes": ids,   # junction centre nodes boxed as orange endpoints
            }

    # ── 2c. Junction-topology fallback from inline path_lists ────────────────
    # Fires when query already returned full trace_nodes lists (rare; most
    # Phase-5 queries return only the centre node via j.trace_nodes[1]).
    if intent_type == "segment_junction_topology" and path_lists:
        traces = [
            {
                "lps_id": f"junction_path_{i+1}",
                "trace_nodes": path,
                "flow_state": "UNKNOWN",
                "flow_direction": None,
                "flow_confidence": None,
            }
            for i, path in enumerate(path_lists)
            if len(path) >= 2
        ]
        if traces:
            return {
                "mode":           "pipes",
                "node_ids":       [],
                "labels":         [],
                "pipe_traces":    traces,
                "endpoint_nodes": ids,
            }

    # ── 2d. Dead-end pipe segments: render LPS traces for dead-end runs ─────
    # When the query specifically targets dead-end pipe stubs (drawing_consistency
    # dangling-end sub-intent), fetch the LPS traces covering those PipeSegments
    # so engineers see the exact pipe runs that dead-end, not just connector boxes.
    _dead_seg_intents = {"drawing_consistency", "isolation_reachability"}
    _dead_seg_issue_keywords = {"dead", "dangling", "dead_end", "stub", "blind"}
    if (
        intent_type in _dead_seg_intents
        and any(w in q_lower for w in _dead_seg_issue_keywords)
        and not lps_ids
    ):
        dead_traces = _fetch_dead_segment_traces(pid_id)
        if dead_traces:
            # node boxes from ids (equipment endpoints) show alongside the pipe traces
            return {
                "mode":           "pipes",
                "node_ids":       [],
                "labels":         [],
                "pipe_traces":    dead_traces,
                "endpoint_nodes": ids,
            }

    # ── Check if these are violation records ─────────────────────────────────
    _is_violation_result = any(
        _first_scalar_value(r, "rule_name", "rule_id", "severity")
        for r in records
    )

    if ids and _is_violation_result:
        # Violation-specific highlight: include severities, explanations, and context nodes
        # (anchor node not needed here — violations highlight the problematic node)
        sevs: Dict[str, str] = {}
        expls: Dict[str, str] = {}
        rules: Dict[str, str] = {}
        for r in records:
            nid = _first_node_id_from_record(r, node_universe)
            if not nid:
                continue
            sev = _first_scalar_value(r, "severity")
            if sev:
                sev = str(sev)
                # Keep the highest severity per node
                SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
                if nid not in sevs or SEV_ORDER.get(sev, 9) < SEV_ORDER.get(sevs[nid], 9):
                    sevs[nid] = sev
            expl = str(_first_scalar_value(r, "explanation") or "")
            rule = str(_first_scalar_value(r, "rule_name", "rule_id") or "")
            if expl:
                # Accumulate explanations per node (may have multiple violations)
                friendly_rule = str(_ISSUE_DISPLAY_NAME.get(rule, rule) or rule)
                if nid in expls:
                    expls[nid] += "\n" + friendly_rule + ": " + expl
                else:
                    expls[nid] = friendly_rule + ": " + expl
            if rule:
                friendly = str(_ISSUE_DISPLAY_NAME.get(rule, rule) or rule)
                if nid in rules:
                    rules[nid] += ", " + friendly
                else:
                    rules[nid] = friendly

        # Fetch PIPE neighbors to give reasoning context on the diagram
        neighbors = _fetch_pipe_neighbors(ids, pid_id)
        # Collect all neighbor IDs not already in the primary set
        context_ids = []
        for nid in ids:
            for nbr in neighbors.get(nid, []):
                if nbr not in ids and nbr not in context_ids:
                    context_ids.append(nbr)

        return {
            "mode":         "ids",
            "node_ids":     ids,
            "labels":       [],
            "severities":   sevs,
            "explanations": expls,
            "rules":        rules,
            "context_nodes": context_ids,
            "neighbors":    neighbors,
        }

    if ids:
        # Always include the queried symbol alongside any result nodes
        all_ids = list(dict.fromkeys(filter(None, ids + ([anchor_node] if anchor_node else []))))
        return {"mode": "ids", "node_ids": all_ids, "labels": []}

    # Inventory count/aggregate answers should still produce a visual mapping
    # when the question is explicitly symbol-oriented.
    if intent_type == "engineering_inventory":
        inv = _infer_inventory_highlight(records, question, pid_id)
        if inv:
            return inv

    # Cross-domain quality summary (e.g. "equipment with quality annotation")
    # often returns grouped counts, not node ids.
    if intent_type == "cross_domain" and records and (
        ("quality" in q_lower and "annotation" in q_lower)
        or ("flagged" in q_lower and "review" in q_lower)
    ):
        cross_issue_types = list(
            _DEFECT_ISSUES | _PIPE_SEGMENT_DEFECTS | _TOPOLOGY_ISSUES | _PIPE_SEGMENT_INFO
        )
        flagged = _lookup_node_ids_for_issues(cross_issue_types, pid_id, allow_topology=True)
        if flagged:
            return {
                "mode": "ids",
                "node_ids": list(dict.fromkeys(r["node_id"] for r in flagged if r.get("node_id"))),
                "labels": [],
            }

    if intent_type == "cross_domain" and records and (
        "esv" in q_lower or "equipment semantics" in q_lower
    ):
        esv_ids = _lookup_node_ids_by_annotation_category(pid_id, "ESV")
        if esv_ids:
            return {"mode": "ids", "node_ids": esv_ids, "labels": []}
        return {
            "mode": "labels",
            "node_ids": [],
            "labels": ["tank", "valve", "instrumentation", "inlet/outlet"],
        }

    # 2. Quality / consistency / engineering-violation intents
    # isolation_reachability is included here because component/orphan queries
    # should highlight the actual isolated nodes, not a generic label class.
    quality_intents = {
        "drawing_consistency", "engineering_correctness",
        "annotation_requests", "engineering_violations",
        "isolation_reachability",
    }
    if intent_type in quality_intents:
        # annotation_requests: AnnotationRequest nodes are not Annotation nodes;
        # query their targets directly instead of using the issue-type lookup.
        if intent_type == "annotation_requests":
            ar_ids = _lookup_annotation_request_node_ids(pid_id)
            if ar_ids:
                return {"mode": "ids", "node_ids": ar_ids, "labels": []}
            return {"mode": "none", "node_ids": [], "labels": []}

        issue_types: List[str] = []
        for r in records:
            issue = _first_scalar_value(r, "issue_type", "type", "rule_name", "rule_id")
            if not issue:
                continue
            issue_str = str(issue).strip()
            if issue_str and issue_str not in issue_types:
                issue_types.append(issue_str)

        if issue_types and all(t in {"direction_observation", "direction_frequency_summary"} for t in issue_types):
            issue_types = []

        explicitly_topology = bool(
            issue_types and any(
                t in (_TOPOLOGY_ISSUES | _PIPE_SEGMENT_DEFECTS | _PIPE_SEGMENT_INFO)
                for t in issue_types if t
            )
        )

        if not issue_types:
            # Per-intent defaults when no issue types found in records
            if intent_type == "isolation_reachability":
                # Show actual orphaned / structurally isolated nodes
                issue_types = ["orphan_node"]
            elif intent_type == "engineering_correctness":
                # Show Phase 3.5 engineering violations (most relevant to correctness)
                issue_types = list(_ENGINEERING_VIOLATIONS)
            else:
                # drawing_consistency / engineering_violations: full defect sweep
                issue_types = list(
                    _DEFECT_ISSUES | _PIPE_SEGMENT_DEFECTS | _TOPOLOGY_ISSUES | _PIPE_SEGMENT_INFO
                )

        flagged = _lookup_node_ids_for_issues(
            issue_types, pid_id, allow_topology=explicitly_topology
        )
        if flagged:
            flagged_ids = [r["node_id"] for r in flagged]
            sevs_map = {
                r["node_id"]: (
                    r.get("severity")
                    or _VIOLATION_SEVERITY.get(r.get("issue_type",""), None)
                )
                for r in flagged
                if r.get("issue_type","") in _ENGINEERING_VIOLATIONS
            }
            expls_map = {
                r["node_id"]: r.get("explanation", "")
                for r in flagged
                if r.get("explanation")
            }

            # Fetch context nodes for violation highlights
            viol_node_ids = [r["node_id"] for r in flagged
                             if r.get("issue_type","") in _ENGINEERING_VIOLATIONS]
            neighbors = _fetch_pipe_neighbors(viol_node_ids, pid_id) if viol_node_ids else {}
            context_ids = []
            for nid in viol_node_ids:
                for nbr in neighbors.get(nid, []):
                    if nbr not in flagged_ids and nbr not in context_ids:
                        context_ids.append(nbr)

            return {
                "mode":         "ids",
                "node_ids":     flagged_ids,
                "labels":       [],
                "severities":   sevs_map,
                "explanations": expls_map,
                "context_nodes": context_ids,
                "neighbors":    neighbors,
            }
        return {"mode": "none", "node_ids": [], "labels": []}
        # Note: anchor_node not useful for quality intents — they show defect-based nodes

    # Rarity/redundancy aggregate answers commonly return annotation IDs only.
    if intent_type == "redundancy_patterns":
        ann_types: List[str] = []
        pattern_types: List[str] = []
        for r in records:
            ann_t = _first_scalar_value(r, "type")
            pat_t = _first_scalar_value(r, "pattern_type")
            if ann_t:
                ann_t_str = str(ann_t).strip()
                if ann_t_str and ann_t_str not in ann_types:
                    ann_types.append(ann_t_str)
            if pat_t:
                pat_t_str = str(pat_t).strip()
                if pat_t_str and pat_t_str != "__summary__" and pat_t_str not in pattern_types:
                    pattern_types.append(pat_t_str)
        default_ann_types = ["structural_pattern_rarity", "rare_motif_local"]
        if not ann_types:
            ann_types = list(default_ann_types)
        rarity_rows = _lookup_node_ids_for_rarity(pid_id, ann_types=ann_types, pattern_types=pattern_types)
        if not rarity_rows:
            rarity_rows = _lookup_node_ids_for_rarity(
                pid_id,
                ann_types=default_ann_types,
                pattern_types=[],
            )
        if rarity_rows:
            rarity_ids = list(dict.fromkeys(
                str(r.get("node_id") or "").strip() for r in rarity_rows if r.get("node_id")
            ))
            rarity_ids = [nid for nid in rarity_ids if nid]
            if rarity_ids:
                return {"mode": "ids", "node_ids": rarity_ids, "labels": []}

    # 3. Label-aggregate records
    labels = []
    for r in records:
        for f in _LABEL_FIELDS:
            raw = _first_scalar_value(r, f)
            mapped = _LABEL_MAP.get(str(raw or "").lower().strip())
            if mapped and mapped not in labels:
                labels.append(mapped)
        # Generic fallback: capture unseen aliases ending in _type/_label.
        for full, base, raw in _iter_record_entries(r):
            if not (full.endswith("_type") or base.endswith("_type") or full.endswith("_label") or base.endswith("_label")):
                continue
            if raw is None or isinstance(raw, (list, dict)):
                continue
            mapped = _LABEL_MAP.get(str(raw).lower().strip())
            if mapped and mapped not in labels:
                labels.append(mapped)
    if labels:
        return {"mode": "labels", "node_ids": [], "labels": labels}

    # 4. Intent-class fallback
    fb = _INTENT_LBLS.get(intent_type, [])
    if fb:
        return {"mode": "labels", "node_ids": [], "labels": fb}

    # 5. Anchor fallback: highlight the queried symbol even when no result rows.
    # Exception: connectivity_topology with 0 records means the node either doesn't
    # exist on this PID or has no flow path — don't show a phantom "1 highlighted".
    if anchor_node and not (intent_type == "connectivity_topology" and not records):
        return {"mode": "ids", "node_ids": [anchor_node], "labels": []}

    return {"mode": "none", "node_ids": [], "labels": []}


# ── Routes ────────────────────────────────────────────────────────────────────

# Validates PID IDs from HTTP path/query parameters.
# Prevents DoS via oversized inputs and rejects obviously malformed IDs.
_SAFE_PID_RE = re.compile(r'^[A-Za-z0-9_\-]{1,80}$')


def _validate_pid_id(pid_id: str) -> Optional[str]:
    """Return an error string if pid_id is invalid, or None if safe."""
    if len(pid_id) > 100:
        return f"PID ID too long ({len(pid_id)} chars; max 100)"
    if not _SAFE_PID_RE.match(pid_id):
        return "Invalid PID ID format — only alphanumeric, hyphen, and underscore allowed"
    return None


def _internal_error(exc: Exception) -> Any:
    """
    Return a generic 500 response without leaking internal exception detail.
    The real exception is printed server-side for diagnostics.
    """
    print(f"[SERVER] Internal error: {type(exc).__name__}: {exc}")
    return jsonify({"error": "An internal server error occurred."}), 500


@app.route("/")
def index():
    ui = PROJECT_ROOT / "ui"
    if (ui / "index.html").exists():
        return send_from_directory(str(ui), "index.html")
    return "<h2>KOS-PID Server running</h2><p>Place ui/index.html to serve the UI.</p>"

@app.route("/api/pids")
def list_pids():
    return jsonify({"pids": _pids, "active": _active_pid})

@app.route("/api/pid", methods=["POST"])
def set_pid():
    global _active_pid
    pid = (request.get_json(silent=True) or {}).get("pid_id","").strip()
    fmt_err = _validate_pid_id(pid) if pid else "pid_id required"
    if fmt_err: return jsonify({"error": fmt_err}), 400
    if pid not in _pids: return jsonify({"error":f"Unknown PID: {pid}"}), 400
    _active_pid = pid
    return jsonify({"active": _active_pid})

@app.route("/api/image/<pid_id>")
def serve_image(pid_id):
    fmt_err = _validate_pid_id(pid_id)
    if fmt_err: return jsonify({"error": fmt_err}), 400
    if pid_id not in _pids: return jsonify({"error":"unknown PID"}), 404
    try:
        return send_file(_resolve_pid_paths(pid_id)["image"], mimetype="image/png")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 404

@app.route("/api/nodes/<pid_id>")
def serve_nodes(pid_id):
    fmt_err = _validate_pid_id(pid_id)
    if fmt_err: return jsonify({"error": fmt_err}), 400
    if pid_id not in _pids: return jsonify({"error":"unknown PID"}), 404
    try:
        return jsonify(_parse_nodes(pid_id))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 404

@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    cleared = list(_node_cache.keys())
    _node_cache.clear()
    print(f"[SERVER] Node cache cleared: {cleared}")
    return jsonify({"cleared": cleared})

@app.route("/api/violations/<pid_id>")
def get_violations(pid_id):
    """
    Return a summary of Phase 3.5 engineering rule violations for a PID.

    Response:
        {
            "total": int,
            "by_severity": {"CRITICAL": int, "HIGH": int, "MEDIUM": int},
            "by_pattern": {"missing_check_valve": int, ...},
            "violations": [
                {
                    "node_id": str, "label": str, "functional_label": str|null,
                    "issue_type": str, "severity": str, "explanation": str,
                    "skid_type": str|null, "hitl_status": str|null,
                    "reviewed_by": str|null
                }, ...
            ]
        }
    """
    if pid_id not in _pids:
        return jsonify({"error": "unknown PID"}), 404
    fmt_err = _validate_pid_id(pid_id)
    if fmt_err: return jsonify({"error": fmt_err}), 400
    try:
        with _loader.driver.session(database=_loader.database) as s:
            rows = s.run(
                """
                MATCH (a:Annotation {pid_id: $pid_id, type: 'engineering_rule_violation'})
                      -[:ANNOTATES]->(n:Node)
                RETURN n.id              AS node_id,
                       n.label           AS label,
                       n.functional_label AS functional_label,
                       a.pattern_type    AS issue_type,
                       a.severity        AS severity,
                       a.explanation     AS explanation,
                       a.skid_type       AS skid_type,
                      properties(a).hitl_status AS hitl_status,
                      properties(a).reviewed_by AS reviewed_by
                ORDER BY a.severity, a.pattern_type, n.id
                """,
                pid_id=pid_id,
            ).data()

        by_severity: Dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0}
        by_pattern:  Dict[str, int] = {}
        for r in rows:
            sev = str(r.get("severity") or "MEDIUM")
            by_severity[sev] = by_severity.get(sev, 0) + 1
            pt = str(r.get("issue_type") or "")
            by_pattern[pt] = by_pattern.get(pt, 0) + 1

        return jsonify({
            "total":       len(rows),
            "by_severity": by_severity,
            "by_pattern":  by_pattern,
            "violations":  rows,
        })
    except Exception as exc:
        return _internal_error(exc)


@app.route("/api/hitl/queue/<pid_id>")
def get_hitl_queue(pid_id: str):
    """
    Return the full HITL review queue for a PID (all items, any status).

    Response:
        {
            "pid_id": str, "total": int, "pending": int,
            "items": [
                {
                    "ann_id": str, "source": str, "pattern_type": str,
                    "severity": str, "description": str,
                    "hitl_status": "PENDING"|"APPROVED"|"REJECTED"|"SKIPPED",
                    "reviewed_by": str|null, "node_id": str|null
                }, ...
            ]
        }
    """
    fmt_err = _validate_pid_id(pid_id)
    if fmt_err: return jsonify({"error": fmt_err}), 400
    if pid_id not in _pids: return jsonify({"error": "unknown PID"}), 404
    try:
        with _loader.driver.session(database=_loader.database) as s:
            v_rows = s.run(
                """
                MATCH (a:Annotation {pid_id: $pid_id, type: 'engineering_rule_violation'})
                OPTIONAL MATCH (a)-[:ANNOTATES]->(n:Node)
                RETURN a.id           AS ann_id,
                       a.pattern_type AS pattern_type,
                       a.severity     AS severity,
                       a.explanation  AS description,
                       properties(a).hitl_status AS hitl_status,
                       properties(a).reviewed_by AS reviewed_by,
                       n.id           AS node_id
                ORDER BY a.severity, a.pattern_type
                """,
                pid_id=pid_id,
            ).data()

            r_rows = s.run(
                """
                MATCH (a:Annotation {
                    pid_id: $pid_id,
                    type: 'structural_pattern_rarity',
                    category: 'KAV'
                })
                WHERE a.hitl_severity IN ['HIGH', 'CRITICAL']
                OPTIONAL MATCH (a)-[:ANNOTATES]->(n:Node)
                RETURN a.id            AS ann_id,
                       a.pattern_type  AS pattern_type,
                       a.hitl_severity AS severity,
                       a.rarity_label  AS rarity_label,
                       properties(a).hitl_status AS hitl_status,
                       properties(a).reviewed_by AS reviewed_by,
                       n.id            AS node_id
                ORDER BY a.hitl_severity, a.pattern_type
                """,
                pid_id=pid_id,
            ).data()

        items: List[Dict[str, Any]] = []
        for v in v_rows:
            items.append({
                "ann_id":       v["ann_id"],
                "source":       "phase3_engineering_rules",
                "pattern_type": v.get("pattern_type") or "",
                "severity":     v.get("severity") or "MEDIUM",
                "description":  v.get("description") or v.get("pattern_type") or "",
                "hitl_status":  v.get("hitl_status") or "PENDING",
                "reviewed_by":  v.get("reviewed_by"),
                "node_id":      v.get("node_id"),
            })
        for r in r_rows:
            items.append({
                "ann_id":       r["ann_id"],
                "source":       "phase3_structural_rarity",
                "pattern_type": r.get("pattern_type") or "",
                "severity":     r.get("severity") or "HIGH",
                "description":  f"{r.get('pattern_type','')} — {r.get('rarity_label','unknown')}",
                "hitl_status":  r.get("hitl_status") or "PENDING",
                "reviewed_by":  r.get("reviewed_by"),
                "node_id":      r.get("node_id"),
            })

        pending = sum(1 for i in items if i["hitl_status"] == "PENDING")
        return jsonify({"pid_id": pid_id, "total": len(items), "pending": pending, "items": items})
    except Exception as exc:
        return _internal_error(exc)


@app.route("/api/hitl/decision", methods=["POST"])
def hitl_decision():
    """
    Record an approve / reject / skip decision for a HITL queue item.

    Request body:
        { "ann_id": str, "action": "approve"|"reject"|"skip",
          "reviewer": str (optional), "note": str (optional) }
    """
    body     = request.get_json(silent=True) or {}
    ann_id   = (body.get("ann_id") or "").strip()
    action   = (body.get("action") or "").strip().lower()
    reviewer = (body.get("reviewer") or "ui_reviewer").strip()[:100]
    note     = (body.get("note") or "").strip()[:500]

    if not ann_id:
        return jsonify({"error": "ann_id required"}), 400
    if action not in {"approve", "reject", "skip"}:
        return jsonify({"error": "action must be approve, reject, or skip"}), 400

    try:
        with _loader.driver.session(database=_loader.database) as s:
            if action == "approve":
                s.run(
                    """
                    MATCH (a:Annotation {id: $ann_id})
                    SET a.hitl_status = 'APPROVED',
                        a.reviewed_by = $reviewer,
                        a.review_note = $note,
                        a.reviewed_at = datetime()
                    """,
                    ann_id=ann_id, reviewer=reviewer, note=note,
                )
            elif action == "reject":
                s.run(
                    """
                    MATCH (a:Annotation {id: $ann_id})
                    SET a.hitl_status      = 'REJECTED',
                        a.reviewed_by      = $reviewer,
                        a.rejection_reason = $note,
                        a.reviewed_at      = datetime()
                    """,
                    ann_id=ann_id, reviewer=reviewer, note=note,
                )
            # skip: no DB write — item remains PENDING until explicitly decided
        return jsonify({"ok": True, "action": action, "ann_id": ann_id})
    except Exception as exc:
        return _internal_error(exc)


@app.route("/api/hitl/finalize/<pid_id>", methods=["POST"])
def hitl_finalize(pid_id: str):
    """
    Run Per-Skid Corpus + Global Statistical Knowledge Layer steps,
    then stamp pid.status = 'PHASE7_COMPLETE'.

    Requires pid.status in {PHASE6_COMPLETE, PHASE7_COMPLETE}.
    """
    fmt_err = _validate_pid_id(pid_id)
    if fmt_err: return jsonify({"error": fmt_err}), 400
    if pid_id not in _pids: return jsonify({"error": "unknown PID"}), 404
    try:
        from engine.phase3_annotation.skid_corpus_rarity import build_skid_corpus
        from engine.phase3_annotation.global_statistics import build_global_statistics

        with _loader.driver.session(database=_loader.database) as s:
            ctx = s.run(
                """
                MATCH (plant:Plant)-[:HAS_SKID]->(skid:Skid)
                      -[:HAS_PID]->(pid:PID {pid_id: $pid_id})
                RETURN plant.plant_id AS plant_id,
                       skid.skid_id   AS skid_id,
                       pid.status     AS status
                """,
                pid_id=pid_id,
            ).single()

        if ctx is None:
            return jsonify({"error": f"PID '{pid_id}' not found in plant hierarchy"}), 404

        plant_id: str = ctx["plant_id"]
        skid_id:  str = ctx["skid_id"]
        status:   str = ctx["status"]

        if status not in {"PHASE6_COMPLETE", "PHASE7_COMPLETE"}:
            return jsonify({
                "error": f"PID status is '{status}'; expected PHASE6_COMPLETE. "
                         "Complete Phase 0–6 before finalizing Phase 7."
            }), 400

        with _loader.driver.session(database=_loader.database) as s:
            corpus_result = build_skid_corpus(s, skid_id)
            global_result = build_global_statistics(s, plant_id)

        with _loader.driver.session(database=_loader.database) as s:
            s.run(
                "MATCH (pid:PID {pid_id: $pid_id}) SET pid.status = 'PHASE7_COMPLETE'",
                pid_id=pid_id,
            )

        print(f"[SERVER] Phase 7 finalized for PID={pid_id}")
        return jsonify({
            "ok":           True,
            "pid_id":       pid_id,
            "status":       "PHASE7_COMPLETE",
            "corpus":       corpus_result,
            "global_stats": global_result,
        })
    except Exception as exc:
        print(f"[SERVER] hitl_finalize error: {exc}")
        return _internal_error(exc)


@app.route("/api/query", methods=["POST"])
def query():
    body     = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    pid_id   = (body.get("pid_id") or _active_pid).strip()
    if not question: return jsonify({"error":"question required"}), 400
    # Validate pid_id format and ensure it is a known PID.
    # Reject "UNKNOWN" explicitly — _pid() returns "" for it, leaking all PIDs.
    fmt_err = _validate_pid_id(pid_id)
    if fmt_err:
        return jsonify({"error": fmt_err}), 400
    if pid_id not in _pids:
        return jsonify({"error": "unknown PID"}), 404

    try:
        result = _agent.answer(question, pid_id=pid_id)

    except Exception as exc:
        msg = str(exc)
        if "AmbiguityError" in type(exc).__name__ or "candidates" in msg.lower():
            return jsonify({
                "error":  "ambiguous",
                "answer": "That question matches multiple query types. Could you be more specific? "
                          "For example: 'list all valves', 'count valves', 'show dangling valves'.",
            }), 200
        if "rate_limit" in msg or "429" in msg:
            import re as _re
            wait = _re.search(r'try again in ([^.]+)', msg)
            wait_str = wait.group(1) if wait else "a few minutes"
            return jsonify({
                "error":  "rate_limit",
                "answer": f"Groq daily token limit reached. Please wait {wait_str} and try again.",
            }), 200
        print(f"[SERVER] query error: {type(exc).__name__}: {exc}")
        return jsonify({"error": msg}), 500

    intent_type = result["intent"].get("intent_type","")
    records     = result.get("records",[])
    anchor_node = str(result["intent"].get("slots", {}).get("tag") or "").strip()

    answer_text = _sanitise_answer(result["answer"])
    if intent_type == "connectivity_topology" and not records and anchor_node:
        try:
            with _loader.driver.session(database=_loader.database) as _s:
                _row = _s.run(
                    "MATCH (n:Node {id: $nid, pid_id: $pid}) RETURN n.id LIMIT 1",
                    nid=anchor_node, pid=pid_id,
                ).single()
            if not _row:
                answer_text = (
                    f"**{anchor_node}** does not exist on this drawing ({pid_id}). "
                    f"Try switching to the PID that contains {anchor_node} using the dropdown."
                )
        except Exception:
            pass

    return jsonify({
        "answer":       answer_text,
        "intent":       intent_type,
        "strategy":     result.get("strategy",""),
        "cypher":       result.get("cypher",""),
        "records":      records[:50],
        "highlight":    _highlight(records, intent_type, pid_id, anchor_node, question),
        "node_context": _build_node_details(records, intent_type, question, pid_id, anchor_node),
    })


# ── Dashboard / Analytics Endpoints ───────────────────────────────────────────

@app.route("/api/dashboard/<pid_id>")
def get_dashboard(pid_id: str):
    """
    Single-call dashboard payload summarising the complete state of a PID.

    Returns:
        {
            pid_id, plant_id, skid_id, skid_type, status,
            equipment: {valve, tank, instrumentation, inlet_outlet, ...},
            flow_coverage: {total_lps, seeded, propagated, unknown, ...},
            violations: {total, by_severity, by_pattern},
            annotations: {total, by_type_top10},
            annotation_requests: {total, open, resolved},
            quality_issues: {orphan, dead_end, dangling, endpoint_collision, ...},
        }
    """
    fmt_err = _validate_pid_id(pid_id)
    if fmt_err: return jsonify({"error": fmt_err}), 400
    if pid_id not in _pids: return jsonify({"error": "unknown PID"}), 404
    try:
        with _loader.driver.session(database=_loader.database) as s:
            # ── PID context ──
            ctx = s.run(
                """
                MATCH (plant:Plant)-[:HAS_SKID]->(skid:Skid)
                      -[:HAS_PID]->(pid:PID {pid_id: $pid})
                RETURN plant.plant_id  AS plant_id,
                       plant.name      AS plant_name,
                       skid.skid_id    AS skid_id,
                       skid.skid_type  AS skid_type,
                       pid.status      AS status,
                       pid.date        AS date, pid.rev AS rev
                """,
                pid=pid_id,
            ).single()

            # ── Equipment breakdown ──
            equip_rows = s.run(
                """
                MATCH (p:PID {pid_id:$pid})-[:CONTAINS]->(n:Node)
                WHERE n.structural_type = 'SYMBOL'
                  AND n.label <> 'background'
                RETURN coalesce(n.functional_label, n.label) AS symbol_type,
                       count(n) AS total
                ORDER BY total DESC
                """,
                pid=pid_id,
            ).data()

            # ── Flow coverage ──
            flow = s.run(
                """
                MATCH (lps:LogicalPipeSegment {pid_id:$pid})
                WITH count(lps) AS total,
                     sum(CASE WHEN lps.flow_state = 'SEEDED'     THEN 1 ELSE 0 END) AS seeded,
                     sum(CASE WHEN lps.flow_state = 'PROPAGATED' THEN 1 ELSE 0 END) AS propagated,
                     sum(CASE WHEN lps.flow_state = 'UNKNOWN'    THEN 1 ELSE 0 END) AS unknown,
                     sum(CASE WHEN lps.flow_state = 'BLOCKED'    THEN 1 ELSE 0 END) AS blocked,
                     avg(CASE WHEN lps.flow_confidence IS NOT NULL THEN lps.flow_confidence END) AS avg_conf
                RETURN total, seeded, propagated, unknown, blocked, avg_conf
                """,
                pid=pid_id,
            ).single()

            # ── Violations ──
            viols = s.run(
                """
                MATCH (a:Annotation {pid_id:$pid, type:'engineering_rule_violation'})
                RETURN a.severity AS sev, a.pattern_type AS pt, count(*) AS cnt
                """,
                pid=pid_id,
            ).data()

            # ── Annotation counts by type (quality issues) ──
            ann_counts = s.run(
                """
                MATCH (a:Annotation {pid_id:$pid})
                WHERE a.type <> 'direction_observation'
                  AND a.type <> 'direction_frequency_summary'
                RETURN a.type AS type, count(*) AS cnt
                ORDER BY cnt DESC
                """,
                pid=pid_id,
            ).data()

            # ── Annotation requests ──
            ar = s.run(
                """
                MATCH (ar:AnnotationRequest {pid_id:$pid})
                RETURN ar.status AS status, count(*) AS cnt
                """,
                pid=pid_id,
            ).data()

        # Build response
        equip = {r["symbol_type"]: r["total"] for r in equip_rows}

        by_sev: Dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0}
        by_pat: Dict[str, int] = {}
        for v in viols:
            by_sev[v["sev"]] = by_sev.get(v["sev"], 0) + v["cnt"]
            by_pat[v["pt"]] = by_pat.get(v["pt"], 0) + v["cnt"]
        viol_total = sum(by_sev.values())

        quality: Dict[str, int] = {}
        ann_total = 0
        for ac in ann_counts:
            quality[ac["type"]] = ac["cnt"]
            ann_total += ac["cnt"]

        ar_by_status = {r["status"]: r["cnt"] for r in ar}
        ar_total = sum(ar_by_status.values())
        ar_open = ar_by_status.get("open", 0) + ar_by_status.get("pending", 0)

        flow_total = flow["total"] if flow else 0
        flow_resolved = ((flow["seeded"] or 0) + (flow["propagated"] or 0)) if flow else 0

        return jsonify({
            "pid_id":    pid_id,
            "plant_id":  ctx["plant_id"] if ctx else None,
            "plant_name": ctx["plant_name"] if ctx else None,
            "skid_id":   ctx["skid_id"] if ctx else None,
            "skid_type": ctx["skid_type"] if ctx else None,
            "status":    ctx["status"] if ctx else None,
            "date":      ctx["date"] if ctx else None,
            "rev":       ctx["rev"] if ctx else None,
            "equipment": equip,
            "flow_coverage": {
                "total_lps":  flow_total,
                "seeded":     flow["seeded"] if flow else 0,
                "propagated": flow["propagated"] if flow else 0,
                "unknown":    flow["unknown"] if flow else 0,
                "blocked":    flow["blocked"] if flow else 0,
                "resolved":   flow_resolved,
                "pct":        round(flow_resolved / flow_total * 100, 1) if flow_total else 0,
                "avg_confidence": round(flow["avg_conf"], 3) if flow and flow["avg_conf"] else None,
            },
            "violations": {
                "total":       viol_total,
                "by_severity": by_sev,
                "by_pattern":  by_pat,
            },
            "annotations": {
                "total":       ann_total,
                "by_type":     quality,
            },
            "annotation_requests": {
                "total":    ar_total,
                "open":     ar_open,
                "resolved": ar_total - ar_open,
                "by_status": ar_by_status,
            },
        })
    except Exception as exc:
        print(f"[SERVER] dashboard error: {exc}")
        return _internal_error(exc)


@app.route("/api/flow_evidence/<pid_id>/<lps_id>")
def get_flow_evidence(pid_id: str, lps_id: str):
    """
    Return the evidence chain that determined a pipe segment's flow direction.
    Shows the engineer WHY a particular flow was assigned.
    """
    fmt_err = _validate_pid_id(pid_id)
    if fmt_err: return jsonify({"error": fmt_err}), 400
    if pid_id not in _pids: return jsonify({"error": "unknown PID"}), 404
    if len(lps_id) > 200: return jsonify({"error": "lps_id too long"}), 400
    try:
        with _loader.driver.session(database=_loader.database) as s:
            lps_info = s.run(
                """
                MATCH (lps:LogicalPipeSegment {id:$lps, pid_id:$pid})
                RETURN lps.flow_state      AS flow_state,
                       lps.flow_direction  AS flow_direction,
                       lps.flow_confidence AS flow_confidence,
                       lps.seed_confidence AS seed_confidence,
                       lps.flow_source     AS flow_source,
                       lps.phase4_hint     AS phase4_hint,
                       lps.endpoints       AS endpoints,
                       lps.trace_nodes     AS trace_nodes
                """,
                lps=lps_id, pid=pid_id,
            ).single()

            evidence_rows = s.run(
                """
                MATCH (a:Arrow)-[fe:FLOW_EVIDENCE]->(lps:LogicalPipeSegment {id:$lps, pid_id:$pid})
                RETURN a.id                AS arrow_id,
                       fe.confidence       AS confidence,
                       fe.direction_hint   AS direction_hint,
                       fe.cosine_alignment AS cosine_alignment,
                       fe.dx               AS dx,
                       fe.dy               AS dy,
                       fe.direction_method AS method
                ORDER BY fe.confidence DESC
                """,
                lps=lps_id, pid=pid_id,
            ).data()

            equip_evidence = s.run(
                """
                MATCH (ev:Evidence)-[:ABOUT]->(lps:LogicalPipeSegment {id:$lps, pid_id:$pid})
                RETURN ev.id                 AS evidence_id,
                       ev.observed_direction AS direction,
                       ev.confidence         AS confidence,
                       ev.role               AS role,
                       ev.source             AS source,
                       ev.equipment_id       AS equipment_id,
                       ev.equipment_label    AS equipment_label
                ORDER BY ev.confidence DESC
                """,
                lps=lps_id, pid=pid_id,
            ).data()

        if not lps_info:
            return jsonify({"error": f"LPS '{lps_id}' not found"}), 404

        return jsonify({
            "lps_id":     lps_id,
            "pid_id":     pid_id,
            "flow_state":     lps_info["flow_state"],
            "flow_direction": lps_info["flow_direction"],
            "flow_confidence": float(lps_info["flow_confidence"]) if lps_info["flow_confidence"] is not None else None,
            "seed_confidence": float(lps_info["seed_confidence"]) if lps_info["seed_confidence"] is not None else None,
            "flow_source":    lps_info["flow_source"],
            "phase4_hint":    lps_info["phase4_hint"],
            "endpoints":      lps_info["endpoints"],
            "trace_nodes":    lps_info["trace_nodes"],
            "arrow_evidence": evidence_rows,
            "equipment_evidence": equip_evidence,
        })
    except Exception as exc:
        return _internal_error(exc)


# ── Location rationale engine ──────────────────────────────────────────────────

# Human-readable labels for each graph node label used in rationale prose.
_PROSE_LABEL: Dict[str, str] = {
    "pump":               "pump",
    "tank":               "vessel/tank",
    "valve":              "valve",
    "instrumentation":    "instrument",
    "general":            "inline component",
    "arrow":              "flow arrow",
    "crossing":           "pipe junction",
    "inlet/outlet":       "system boundary",
    "inferred_check_valve": "check valve",
    "inferred_inline_equipment": "inline equipment",
}

# Skid-level descriptions for the "system context" sentence.
_SKID_DESC: Dict[str, str] = {
    "CONDENSATE":       "condensate collection and return system",
    "STEAM":            "steam generation and distribution system",
    "CHEMICAL_REACTOR": "chemical processing system",
    "COOLING_WATER":    "cooling water recirculation system",
}

# Relationship prose between THIS symbol and a specific neighbor type.
# Keys: (this_fn_label, neighbor_fn_label, relation)  relation = "upstream"|"downstream"|"adjacent"
_NEIGHBOR_CONTEXT: Dict[tuple, str] = {
    # Valve placements
    ("valve", "pump",       "downstream"): "isolates the pump discharge for maintenance",
    ("valve", "pump",       "upstream"):   "provides suction isolation to allow the pump to be taken offline",
    ("valve", "tank",       "upstream"):   "controls flow entering the vessel",
    ("valve", "tank",       "downstream"): "controls flow leaving the vessel",
    ("valve", "inlet/outlet", "upstream"): "isolates this system from the external feed connection",
    ("valve", "inlet/outlet", "downstream"): "isolates the export line from this system",
    # Check valve placements
    ("inferred_check_valve", "pump", "downstream"): "prevents reverse flow from spinning the pump back on shutdown",
    ("check_valve",          "pump", "downstream"): "prevents reverse flow from spinning the pump back on shutdown",
    # Instrument placements
    ("instrumentation", "pump",  "adjacent"): "monitors pump suction or discharge conditions",
    ("instrumentation", "tank",  "adjacent"): "monitors vessel level, pressure, or temperature",
    ("instrumentation", "valve", "adjacent"): "monitors flow or pressure across the valve",
    # Pump placements
    ("pump", "tank",       "upstream"):   "draws fluid from the vessel",
    ("pump", "inlet/outlet", "upstream"): "draws from the external feed",
}


def _classify_neighbor_direction(
    node_id: str,
    lps_id: str,
    flow_direction: Optional[str],
    other_id: str,
) -> str:
    """
    Given our node, an LPS id (format 'A__B'), its flow_direction, and the
    other endpoint id, return 'upstream' | 'downstream' | 'adjacent'.

    FORWARD means flow goes A → B.
    REVERSE means flow goes B → A.
    """
    if not flow_direction or flow_direction not in ("FORWARD", "REVERSE"):
        return "adjacent"
    parts = lps_id.split("__")
    if len(parts) != 2:
        return "adjacent"
    a, b = parts[0].strip(), parts[1].strip()
    # other_id is the far endpoint
    if flow_direction == "FORWARD":
        # flow: a → b
        if a == node_id:
            return "downstream"   # flow leaves us toward other (b)
        elif b == node_id:
            return "upstream"     # flow arrives at us from other (a)
    else:
        # flow: b → a  (REVERSE)
        if b == node_id:
            return "downstream"   # flow leaves us toward other (a)
        elif a == node_id:
            return "upstream"     # flow arrives at us from other (b)
    return "adjacent"


def _generate_location_rationale(
    node_id: str,
    node_label: str,
    functional_label: Optional[str],
    directional_neighbors: List[Dict[str, Any]],
    lps_list: List[Dict[str, Any]],
    skid_type: str,
    skid_desc: str,
) -> str:
    """
    Generate a plain-English explanation of why this node is at this location,
    reasoning from its flow context, neighboring equipment, and system purpose.
    """
    eff_label = functional_label or node_label
    prose_self = _PROSE_LABEL.get(eff_label, node_label)

    # --- Collect directional neighbor context ---
    upstream_names:   List[str] = []
    downstream_names: List[str] = []
    adjacent_names:   List[str] = []

    rel_sentences: List[str] = []

    seen: set = set()
    for nb in directional_neighbors:
        oid      = nb.get("other_id", "")
        olabel   = nb.get("other_label", "")
        ofn      = nb.get("other_fn_label") or olabel
        relation = nb.get("relation", "adjacent")
        if oid in seen:
            continue
        seen.add(oid)

        prose_other = _PROSE_LABEL.get(ofn, olabel)

        if relation == "upstream":
            upstream_names.append(f"{prose_other} {oid}")
        elif relation == "downstream":
            downstream_names.append(f"{prose_other} {oid}")
        else:
            adjacent_names.append(f"{prose_other} {oid}")

        # Specific relationship prose
        ctx_key = (eff_label, ofn, relation)
        if ctx_key in _NEIGHBOR_CONTEXT:
            rel_sentences.append(_NEIGHBOR_CONTEXT[ctx_key])

    # --- Flow summary ---
    flow_states = list({
        (r.get("flow_state") or "UNKNOWN").upper()
        for r in lps_list
        if r.get("flow_state")
    })
    has_confirmed_flow = any(s in ("SEEDED", "PROPAGATED") for s in flow_states)
    all_unknown = all(s == "UNKNOWN" for s in flow_states) if flow_states else True

    flow_dirs = list({
        r.get("flow_direction")
        for r in lps_list
        if r.get("flow_direction")
    })
    flow_dir_str = ""
    if len(flow_dirs) == 1:
        flow_dir_str = "downstream →" if flow_dirs[0] == "FORWARD" else "← upstream"
    elif len(flow_dirs) > 1:
        flow_dir_str = "bidirectional"

    # --- Symbol dict lookup ---
    why_txt = ""
    placement_txt = ""
    try:
        from engine.domain_knowledge.symbol_dictionary import UNIVERSAL_EQUIPMENT
        entry = UNIVERSAL_EQUIPMENT.get(eff_label, {})
        why_txt       = entry.get("why_needed", "")
        placement_txt = entry.get("typical_location", "")
    except Exception:
        pass

    # --- Build the sentences ---
    parts: List[str] = []

    # Sentence 1: position in network
    if upstream_names and downstream_names:
        up_str   = ", ".join(upstream_names[:2])
        down_str = ", ".join(downstream_names[:2])
        parts.append(
            f"This {prose_self} sits between {up_str} (upstream) "
            f"and {down_str} (downstream)"
            + (f" with {flow_dir_str} flow" if flow_dir_str else "")
            + "."
        )
    elif upstream_names:
        up_str = ", ".join(upstream_names[:2])
        parts.append(
            f"This {prose_self} is located downstream of {up_str}"
            + (f" on a {flow_dir_str} flow path" if flow_dir_str else "")
            + "."
        )
    elif downstream_names:
        down_str = ", ".join(downstream_names[:2])
        parts.append(
            f"This {prose_self} feeds into {down_str}"
            + (f" ({flow_dir_str} flow)" if flow_dir_str else "")
            + "."
        )
    elif adjacent_names:
        adj_str = " and ".join(adjacent_names[:2])
        parts.append(f"This {prose_self} is connected to {adj_str}.")
    else:
        parts.append(f"This {prose_self} is present on this drawing.")

    # Sentence 2: system context
    parts.append(
        f"It is part of the {skid_desc or skid_type.lower()} (skid: {skid_type})."
    )

    # Sentence 3: specific relationship reasons
    if rel_sentences:
        parts.append("Its role here: " + "; ".join(dict.fromkeys(rel_sentences))[:200] + ".")

    # Sentence 4: why needed from symbol dict (trim to avoid repetition)
    if why_txt and not rel_sentences:
        parts.append(why_txt[:200])

    # Sentence 5: flow state context
    if all_unknown and lps_list:
        parts.append(
            "Flow direction on this pipe run has not been resolved — "
            "it may require additional flow arrows or engineer review."
        )
    elif has_confirmed_flow and not flow_dir_str:
        parts.append("Flow direction on adjacent pipe runs is resolved.")

    return " ".join(parts)


@app.route("/api/node_detail/<pid_id>/<node_id>")
def get_node_detail(pid_id: str, node_id: str):
    """
    Full detail for a single node: properties, connected pipes, annotations,
    violations, flow evidence, connected equipment.  Engineer-facing deep-dive.
    """
    fmt_err = _validate_pid_id(pid_id)
    if fmt_err: return jsonify({"error": fmt_err}), 400
    if pid_id not in _pids: return jsonify({"error": "unknown PID"}), 404
    if len(node_id) > 200: return jsonify({"error": "node_id too long"}), 400
    try:
        with _loader.driver.session(database=_loader.database) as s:
            node = s.run(
                """
                MATCH (n:Node {id:$nid, pid_id:$pid})
                RETURN n.id              AS id,
                       n.label           AS label,
                       n.functional_label AS functional_label,
                       n.structural_type AS structural_type,
                       n.flow_state      AS flow_state,
                       n.flow_direction  AS flow_direction,
                       n.flow_confidence AS flow_confidence
                """,
                nid=node_id, pid=pid_id,
            ).single()

            if not node:
                return jsonify({"error": f"Node '{node_id}' not found"}), 404

            # Neighbors
            neighbors = s.run(
                """
                MATCH (n:Node {id:$nid, pid_id:$pid})-[:PIPE]-(m:Node)
                RETURN m.id AS id, m.label AS label,
                       coalesce(m.functional_label, m.label) AS display_label
                """,
                nid=node_id, pid=pid_id,
            ).data()

            # LPS this node is an endpoint of
            lps_list = s.run(
                """
                MATCH (n:Node {id:$nid, pid_id:$pid})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
                RETURN lps.id             AS lps_id,
                       lps.flow_state     AS flow_state,
                       lps.flow_direction AS flow_direction,
                       lps.flow_confidence AS flow_confidence
                """,
                nid=node_id, pid=pid_id,
            ).data()

            # Annotations targeting this node
            anns = s.run(
                """
                MATCH (a:Annotation)-[:ANNOTATES]->(n:Node {id:$nid, pid_id:$pid})
                RETURN a.id           AS ann_id,
                       a.type         AS type,
                       a.pattern_type AS pattern_type,
                       a.severity     AS severity,
                       a.explanation  AS explanation,
                       a.rarity_label AS rarity_label,
                       a.hitl_severity AS hitl_severity,
                       properties(a).hitl_status AS hitl_status
                ORDER BY a.severity, a.type
                """,
                nid=node_id, pid=pid_id,
            ).data()

            # Skid context for this PID
            skid_row = s.run(
                """
                MATCH (p:PID {pid_id:$pid})<-[:HAS_PID]-(sk:Skid)
                RETURN coalesce(sk.skid_type,'UNKNOWN') AS skid_type,
                       coalesce(sk.skid_id,'') AS skid_id
                """,
                pid=pid_id,
            ).single()
            skid_type = skid_row["skid_type"] if skid_row else "UNKNOWN"

            # Directional neighbors via LPS endpoint analysis
            dir_rows = s.run(
                """
                MATCH (n:Node {id:$nid, pid_id:$pid})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
                MATCH (other:Node)-[:ENDPOINT_OF]->(lps)
                WHERE other.id <> n.id
                  AND other.structural_type = 'SYMBOL'
                  AND NOT other.label IN ['connector','background','crossing','arrow']
                RETURN lps.id             AS lps_id,
                       lps.flow_state     AS flow_state,
                       lps.flow_direction AS flow_direction,
                       other.id          AS other_id,
                       other.label       AS other_label,
                       coalesce(other.functional_label, other.label) AS other_fn_label
                """,
                nid=node_id, pid=pid_id,
            ).data()

            # Annotate each row with its resolved direction relative to this node
            fn_label = node.get("functional_label") or node.get("label", "")
            dir_neighbors: List[Dict[str, Any]] = []
            for row in dir_rows:
                relation = _classify_neighbor_direction(
                    node_id,
                    row.get("lps_id", ""),
                    row.get("flow_direction"),
                    row.get("other_id", ""),
                )
                dir_neighbors.append({**dict(row), "relation": relation})

            skid_desc = _SKID_DESC.get(skid_type, skid_type.lower() + " system")
            location_rationale = _generate_location_rationale(
                node_id=node_id,
                node_label=node.get("label", ""),
                functional_label=fn_label,
                directional_neighbors=dir_neighbors,
                lps_list=lps_list,
                skid_type=skid_type,
                skid_desc=skid_desc,
            )

        return jsonify({
            "node": dict(node),
            "neighbors": neighbors,
            "pipe_segments": lps_list,
            "annotations": anns,
            "location_rationale": location_rationale,
        })
    except Exception as exc:
        return _internal_error(exc)


@app.route("/api/quality_map/<pid_id>")
def get_quality_map(pid_id: str):
    """
    Return all annotation locations mapped to node IDs for heatmap overlay.
    Groups by annotation type with severity/rarity for colouring.
    """
    fmt_err = _validate_pid_id(pid_id)
    if fmt_err: return jsonify({"error": fmt_err}), 400
    if pid_id not in _pids: return jsonify({"error": "unknown PID"}), 404
    try:
        with _loader.driver.session(database=_loader.database) as s:
            rows = s.run(
                """
                MATCH (a:Annotation {pid_id:$pid})-[:ANNOTATES]->(n:Node)
                RETURN n.id           AS node_id,
                       a.type         AS type,
                       a.pattern_type AS pattern_type,
                       a.severity     AS severity,
                       a.rarity_score AS rarity_score,
                       a.hitl_severity AS hitl_severity
                """,
                pid=pid_id,
            ).data()

        return jsonify({"pid_id": pid_id, "total": len(rows), "items": rows})
    except Exception as exc:
        return _internal_error(exc)

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host",  default="127.0.0.1")
    p.add_argument("--port",  default=8080, type=int)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    print(f"[SERVER] http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
