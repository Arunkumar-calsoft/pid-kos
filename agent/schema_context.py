# agent/schema_context.py
"""
Grounded Schema Context — Single Source of Truth

100% verified against Neo4j property samples + graphml source.
All LLM calls in this agent (SchemaGenerator, IntentConfirmer,
RegistryEnricher) import from here. No schema knowledge anywhere else.

DO NOT edit unless you have re-run the verification queries:
    MATCH (n) WITH labels(n)[0] AS label, keys(n) AS propKeys, n
    UNWIND propKeys AS propKey
    WITH label, propKey, collect(DISTINCT n[propKey])[0..5] AS sample_values
    RETURN label, propKey, sample_values ORDER BY label, propKey
"""
from __future__ import annotations

from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Node labels → confirmed property keys
# (Verified against Neo4j schema dump — all node types present in graph)
# ---------------------------------------------------------------------------

NODE_PROPERTIES: Dict[str, List[str]] = {

    "Arrow": [
        # Arrow is a SEPARATE node type from Node{label:'arrow'}.
        # Node{label:'arrow'}  — drawing symbol, connected via PIPE edges (no FLOW_EVIDENCE)
        # Arrow                — flow evidence carrier, linked via (Arrow)-[:FLOW_EVIDENCE]->(LPS)
        # Always use (a:Arrow)-[:FLOW_EVIDENCE]->(lps:LogicalPipeSegment) for flow evidence queries.
        # Arrow carries no additional properties beyond identity — all evidence is on
        # the FLOW_EVIDENCE relationship or the linked Evidence node.
        "id",           # e.g. "arrow102", "arrow103"
        "pid_id",       # parent PID identifier
    ],

    "LogicalPipeSegment": [
        # A logical pipe segment connects exactly two endpoint Nodes.
        # It is derived from one or more physical PipeSegments and
        # carries the resolved flow direction for that stretch of pipe.
        "id",               # e.g. "arrow102__crossing151"
        "pid_id",
        "flow_state",       # "UNKNOWN" | "SEEDED" | "PROPAGATED"
        "flow_direction",   # "FORWARD" | "REVERSE" — null when flow_state="UNKNOWN"
        "flow_confidence",  # FLOAT 0.0–1.0
        "seed_confidence",  # FLOAT — confidence of the seeding arrow (null if PROPAGATED/UNKNOWN)
        "flow_source",      # "none" | "evidence"
        "phase4_hint",      # optional propagation hint string
        "endpoints",        # LIST[node_id, node_id] — the two endpoint IDs
        "trace_nodes",      # LIST of all node IDs along segment in order
        "via",              # LIST of intermediate connector IDs
        "length",           # INTEGER hop count
        "source",           # always "derived_logical"
        "created_at",
    ],

    "Node": [
        # Every symbol detected on the PID — connectors, equipment,
        # boundary markers, etc.  structural_type partitions the set.
        "id",               # "{label}{int}" e.g. "valve94", "connector306"
        "pid_id",
        "label",            # symbol class — see NODE_LABEL_VALUES
        "original_label",   # set when label was remapped at Phase 0 (e.g. "pump" → "tank")
        "functional_label", # set by Phase 1 classify_equipment: "pump" on small tank nodes
                            # (bbox width < 100px). PUMPS MUST BE QUERIED AS:
                            #   label='tank' AND functional_label='pump'
                            # There is NO label='pump' in the graph.
        "label_inferred",   # BOOLEAN — true when Phase 1 relabeled a 'general' node
        "original_label",   # STRING — audit trail when label was changed by Phase 1
        "structural_type",  # "SYMBOL" | "BOUNDARY" | "CONNECTOR"
        "bbox",             # LIST [xmin, ymin, xmax, ymax]
        "xmin", "xmax", "ymin", "ymax",  # FLOAT pixel coordinates
        "coord_system",     # coordinate reference (e.g. "pixel")
        "flow_state",       # "UNKNOWN" | "SEEDED" | "PROPAGATED"
        "flow_direction",   # "FORWARD" | "REVERSE" | null
        "flow_confidence",  # FLOAT 0.0–1.0
        "flow_source",      # origin of flow assignment
        "flow_pid_id",      # STRING — PID scope for the denormalised flow assignment
        "source",           # always "graphml"
    ],

    "PipeSegment": [
        # A physical pipe segment extracted directly from the graphml.
        # One or more PipeSegments are grouped into a LogicalPipeSegment.
        "id",               # "PS_1", "PS_57"
        "pid_id",
        "segment_status",   # "NORMAL" (only confirmed value)
        "node_count",       # INTEGER — number of nodes on this segment
        "component_id",     # INTEGER — connected component group
        "geometry_hash",    # STRING — fingerprint for duplicate detection
        "source",           # always "derived"
    ],

    "PID": [
        # Top-level drawing node — one per uploaded P&ID.
        "pid_id",           # "PID_2"
        "graphml_path",     # "data/2.graphml"
        "image_path",       # "data/2.png"
        "date",             # drawing date string
        "rev",              # revision string
        "status",           # processing status
    ],

    "Plant": [
        # Facility-level container; owns one or more Skids.
        "plant_id",         # "PLANT_001"
        "name",
    ],

    "Skid": [
        # Process skid; owns one or more PIDs.
        "skid_id",          # "SKID_01"
        "skid_type",        # e.g. "CONDENSATE"
        "plant_id",         # back-reference to parent Plant
    ],

    "Annotation": [
        # Pre-computed quality observation or statistical summary.
        # NEVER recompute checks from scratch — query Annotation.type first.
        "id",
        "pid_id",
        "label",                    # mirrors Node.label of annotated node
        "type",                     # see ANNOTATION_TYPES
        "intent",                   # "observation" | "statistical_summary" | "gap_detection" | "boundary_inference"
        "pattern_type",             # see ANNOTATION_PATTERN_TYPES
        "source",                   # pipeline phase that created this
        "audience",                 # intended consumer (e.g. "engineer")
        "category",                 # broad grouping
        "rarity_score",             # FLOAT 0.0–1.0
        "rarity_label",             # human-readable rarity label
        "hitl_severity",            # human-in-the-loop severity
        "is_canary",                # BOOLEAN — canary test annotation
        "corpus_normalized",        # BOOLEAN
        "propagation_blocked",      # BOOLEAN
        # ---- HITL review (Phase 7) ----
        "hitl_status",              # "APPROVED" | "REJECTED" | null (pending)
        "reviewed_by",              # STRING — reviewer identifier
        "review_note",              # STRING — approval note
        "rejection_reason",         # STRING — rejection reason
        "reviewed_at",              # datetime
        # ---- corpus normalization ----
        "corpus_mean",              # FLOAT — cross-PID mean (set by skid_corpus_rarity)
        "corpus_std",               # FLOAT — cross-PID std dev
        "corpus_total",             # INTEGER — cross-PID total
        "corpus_pid_count",         # INTEGER — number of PIDs in corpus
        "percentile_rank",          # FLOAT 0.0–1.0 — rank within corpus
        # ---- targeting ----
        "node_id",                  # Node ID this annotation targets
        "lps_id",                   # LogicalPipeSegment ID
        "ps_id",                    # PipeSegment ID
        "target_id",                # generic target ID
        # ---- statistical fields ----
        "degree",                   # INTEGER connectivity degree
        "adj_degree",
        "absolute_count",
        "total_observations",
        "n_evidence",
        "lps_count",
        "lps_list",
        "unique_target_count",
        "avg_confidence",
        "min_confidence",
        "normalized_ratio",
        "total_types",
        "kav_types",
        "kav_total",
        "esv_types",
        "esv_total",
        "engineer_review_count",
        "pipeline_integrity_count",
        "motif_chain_count",
        "cycle_length",
        "max_hops_checked",
        # ---- misc ----
        "phase4_hint",
        "inferred_from",
        "equipment_id",
        "role",                     # "inlet" | "outlet" — for equipment semantics annotations
        "directions",               # STRING summary of direction counts on this LPS
        "other_pids",               # STRING — cross-PID context for pattern annotations
        "first_seen", "last_seen", "created_at",
    ],

    "AnnotationRequest": [
        # A human- or system-initiated request for annotation on a Node.
        # Linked from PID via HAS_ANNOTATION and optionally to a Node via CONCERNS.
        "request_id",
        "pid_id",
        "node_id",
        "label",
        "anomaly_type",
        "detail",
        "status",           # confirmed value: "OPEN" (PENDING/RESOLVED not yet observed)
        "source",
        "phase_origin",     # INTEGER — pipeline phase that raised the request
    ],

    "Evidence": [
        # A single directional evidence item created by Phase 3 equipment semantics.
        # NOTE: Arrow-level flow evidence lives on the FLOW_EVIDENCE RELATIONSHIP,
        # not on Evidence nodes. Evidence nodes are created for equipment-specific
        # directional inference (role: upstream/downstream/inlet/outlet).
        # Verified against live DB — properties below are the actual node properties.
        "id",
        "pid_id",
        "observed_direction",   # "FORWARD" | "REVERSE" — canonical resolved value, USE THIS
        "direction_hint",       # "FORWARD" | "REVERSE" | "UNKNOWN"
        "confidence",           # FLOAT 0.0–1.0
        "low_confidence",       # BOOLEAN
        "role",                 # "upstream"|"downstream"|"inlet"|"outlet"|"ambiguous"|null
        "axis",                 # dominant axis: "H" (horizontal) | "V" (vertical) | null
        "source",               # "phase2_flow_evidence"|"phase3_boundary_semantics"|"phase3_equipment_semantics"|"phase3_check_valve"|"phase3_topology_inference"
        "equipment_id",         # ID of the equipment Node this evidence is for
        "equipment_label",      # label of the equipment Node
        "first_seen",
    ],

    "SkidCorpus": [
        # Cross-PID ESV rarity corpus for a single skid.
        # Created by Phase 7 (skid_corpus_rarity.py) when ≥2 PIDs exist.
        # Linked: (SkidCorpus)-[:CORPUS_OF]->(Skid)
        "id",                   # e.g. "corpus_SKID_01"
        "skid_id",
        "pid_count",            # INTEGER — number of PIDs in the corpus
        "pattern_count",        # INTEGER — number of ESV patterns normalized
        "annotations_updated",  # INTEGER — number of rarity Annotations updated
        "created_at",
        "updated_at",
    ],

    "GlobalStatistic": [
        # Cross-skid ESV frequency baseline for a plant.
        # Created by Phase 7 (global_statistics.py).
        # Phase 4 FSM reads these to adjust seed_confidence:
        #   globally_rare → boost, globally_dominant → reduce.
        # Linked: (GlobalStatistic)-[:STATISTICS_OF]->(Plant)
        "id",                   # e.g. "gstat_structural_branch"
        "pattern_type",         # ESV pattern name
        "category",             # always "ESV"
        "plant_id",
        "global_mean",          # FLOAT — mean unique_target_count across PIDs
        "global_std",           # FLOAT — standard deviation
        "global_total",         # INTEGER — sum of absolute_count across PIDs
        "global_pid_count",     # INTEGER — number of contributing PIDs
        "skid_count",           # INTEGER — number of contributing skids
        "global_rarity",        # tier: globally_absent|globally_rare|globally_typical|globally_common|globally_dominant
                                # NOTE: 'globally_uncommon' does NOT exist in live data — do not use it in queries
        "global_rarity_score",  # FLOAT 0.0–1.0
        "created_at",
        "updated_at",
    ],

    "GlobalStatisticsSummary": [
        # Top-level summary of global statistics for a plant.
        # Linked: (GlobalStatisticsSummary)-[:SUMMARY_OF]->(Plant)
        "id",                   # e.g. "gstat_summary_PLANT_001"
        "plant_id",
        "pattern_count",        # INTEGER — number of GlobalStatistic nodes
        "total_pids",           # INTEGER
        "total_skids",          # INTEGER
        "created_at",
        "updated_at",
    ],
}


# ---------------------------------------------------------------------------
# Confirmed enum / vocabulary values
# ---------------------------------------------------------------------------

NODE_LABEL_VALUES = [
    "connector",        # CONNECTOR structural_type — pipe path intermediate, always degree=2
    "background",       # BOUNDARY structural_type — isolated artifact/noise, always degree=0
    "tank",             # SYMBOL — main process vessel; also used for pump units (functional_label='pump')
    "valve",            # SYMBOL — control/isolation valve
    "instrumentation",  # SYMBOL — instrument (FT, LT, TE, PSV …)
    "general",          # SYMBOL — unclassified symbol (nozzle, reducer, fitting)
    "arrow",            # SYMBOL — flow direction arrow, always degree=2
    "crossing",         # SYMBOL — pipe crossing or junction point
    "inlet/outlet",     # SYMBOL — external system connection, always degree=1
]
# NOTE: There is NO label='pump' in the graph.
# Pump units (CND-PU-xxx) appear as label='tank' with functional_label='pump'.
# Query for pumps with:  n.label = 'tank' AND n.functional_label = 'pump'

STRUCTURAL_TYPES = {
    # Only two structural_type values exist in the live DB.
    # background nodes are filtered by normalize_nodes.py at Phase 0
    # and never loaded into Neo4j — structural_type='BOUNDARY' does not appear.
    "CONNECTOR": "label='connector' — pipe path intermediate, always degree=2",
    "SYMBOL":    "equipment and process symbols: tank, valve, instrumentation, general, arrow, crossing, inlet/outlet",
    # NOTE: 'BOUNDARY' is documented in QUERY_RULES as a value to NEVER query for.
    # It does not exist in the live DB. label='background' nodes are excluded pre-load.
}

EQUIPMENT_LABEL_VALUES = ["instrumentation", "inlet/outlet", "valve", "tank"]

# LPS flow_state values (confirmed from live DB):
#   SEEDED        — direction confirmed from arrow evidence
#   PROPAGATED    — direction inferred by BFS from nearby seeded LPS
#   UNKNOWN       — no direction could be determined; flow_direction is null
#   BLOCKED       — propagation blocked by Phase 3.5 safety violation
#   SEEDED_UNKNOWN— has arrow evidence but direction is contradictory; flow_direction is null
FLOW_STATES      = ["UNKNOWN", "SEEDED", "PROPAGATED", "BLOCKED", "SEEDED_UNKNOWN"]
FLOW_DIRECTIONS  = ["FORWARD", "REVERSE", "UNKNOWN"]   # also null when flow_state=UNKNOWN/BLOCKED/SEEDED_UNKNOWN

ANNOTATION_INTENTS = [
    "observation",
    "equipment_semantics",
    "statistical_summary",
    "topology_inference",
]

# Verified from live DB: MATCH (a:Annotation) RETURN DISTINCT a.type ORDER BY a.type
ANNOTATION_TYPES = [
    # ── Directional / flow evidence ──────────────────────────────────────
    "direction_observation",            # → LogicalPipeSegment
    "direction_frequency_summary",      # → LogicalPipeSegment (statistical)
    # NOTE: direction_evidence_missing is no longer an Annotation node.
    # Gaps are tracked via lps.phase4_hint = 'direction_evidence_missing'
    # and reflected in lps.flow_state = 'UNKNOWN' after Phase 4.
    "lps_low_confidence_evidence",      # → LogicalPipeSegment (confidence < threshold)
    "ps_unreachable_from_evidence",     # → PipeSegment (cannot trace from any evidence)

    # ── Structural topology ───────────────────────────────────────────────
    "orphan_node",                      # → Node (degree=0, no connections)
    "dead_end_pipe_segment",            # → PipeSegment (single-end segment)
    "structural_branch",                # → Node (degree=3, branch point)
    "structural_t_junction",            # → Node (T-shaped junction)
    "structural_high_degree",           # → Node (unusually high degree)
    "pipe_junction",                    # → Node (general pipe junction)
    "pipe_segment_cycle_member",        # → PipeSegment (part of a loop/cycle)
    "large_manifold_node",              # → Node (manifold with very high degree)
    "endpoint_collision",               # → Node (endpoint overlap)

    # ── Logical/Physical mapping ──────────────────────────────────────────
    "pipe_segment_no_logical_mapping",  # → PipeSegment (no LPS covers this PS)
    "pipe_segment_no_evidence_via_lps", # → PipeSegment (LPS has no flow evidence)

    # ── Engineering rule violations ──────────────────────────────────────
    "engineering_rule_violation",        # → Node (Phase 3.5 rule check: missing_check_valve, etc.)

    # ── Cross-PID / consensus ─────────────────────────────────────────────
    "cross_pid_shared_node",             # → Node (shared across PIDs)
    "direction_conflict_observed",       # → LogicalPipeSegment (conflicting evidence)
    "lps_direction_unresolved",          # → LogicalPipeSegment (direction not resolved)
    "lps_weak_evidence_consensus",       # → LogicalPipeSegment (weak consensus)

    # ── Statistical / rarity ──────────────────────────────────────────────
    "rare_motif_local",                 # → PipeSegment
    "structural_pattern_frequency",     # → Annotation (statistical summary)
    "structural_pattern_rarity",        # → Annotation (rarity score record)
]

# Confirmed from live DB pattern_type values (MATCH (a:Annotation) RETURN DISTINCT a.pattern_type)
ANNOTATION_PATTERN_TYPES = [
    "structural_branch",
    "structural_t_junction",
    "structural_high_degree",
    "dead_end_pipe_segment",
    "orphan_node",
    "pipe_segment_cycle_member",
    "pipe_junction",
    "pipe_segment_no_logical_mapping",
    "pipe_segment_no_evidence_via_lps",
    "large_manifold_node",
    "endpoint_collision",
    "rare_motif_local",
    "ps_unreachable_from_evidence",
    "cross_pid_shared_node",
    "lps_direction_unresolved",
    "lps_weak_evidence_consensus",
    "direction_conflict_observed",
    "engineering_rule_violation",
]

ANNOTATION_TYPE_TARGET: Dict[str, str] = {
    # — Directional / flow evidence —
    "direction_observation":            "LogicalPipeSegment",
    "direction_frequency_summary":      "LogicalPipeSegment",
    "direction_conflict_observed":      "LogicalPipeSegment",
    "lps_direction_unresolved":         "LogicalPipeSegment",
    "lps_weak_evidence_consensus":      "LogicalPipeSegment",
    "ps_unreachable_from_evidence":     "PipeSegment",
    # — Structural topology —
    "orphan_node":                      "Node",
    "dead_end_pipe_segment":            "PipeSegment",
    "structural_branch":                "Node",
    "structural_t_junction":            "Node",
    "structural_high_degree":           "Node",
    "pipe_junction":                    "Node",
    "pipe_segment_cycle_member":        "PipeSegment",
    "large_manifold_node":              "Node",
    "endpoint_collision":               "Node",
    # — Logical/Physical mapping —
    "pipe_segment_no_logical_mapping":  "PipeSegment",
    "pipe_segment_no_evidence_via_lps": "PipeSegment",
    # — Engineering / rule violations —
    "engineering_rule_violation":       "Node",
    # — Cross-PID —
    "cross_pid_shared_node":            "Node",
    # — Statistical / rarity —
    "rare_motif_local":                 "PipeSegment",
    "structural_pattern_frequency":     "Annotation",
    "structural_pattern_rarity":        "Annotation",
}


# ---------------------------------------------------------------------------
# Relationships — confirmed traversal patterns
#
# Schema dump key findings vs. old file:
#   • PIPE  (Node→Node)  replaces the old phantom "CONNECTED" relationship.
#     PIPE is the real undirected pipe connection in the graph.
#     It carries edge_label, flow_direction, source.
#   • ADJACENT_VIA_NODES exists on BOTH LogicalPipeSegment and PipeSegment.
#   • JOINS_AT  is PipeSegment→PipeSegment (junction topology).
#   • HAS_ANNOTATION  is PID→AnnotationRequest.
#   • CONCERNS  is AnnotationRequest→Node.
#   • Equipment node is NOT present in the dump — removed.
#   • All relationship directions verified against dump "direction" field.
#
# Format: (from_label, rel_type, to_label, rel_property_keys)
# ---------------------------------------------------------------------------

RELATIONSHIPS: List[Tuple[str, str, str, List[str]]] = [
    # ── Hierarchy ──────────────────────────────────────────────────────────
    ("Plant",              "HAS_SKID",            "Skid",               []),
    ("Skid",               "HAS_PID",             "PID",                []),
    ("PID",                "CONTAINS",            "Node",               []),

    # ── Annotation requests ────────────────────────────────────────────────
    ("PID",                "HAS_ANNOTATION",      "AnnotationRequest",  []),
    ("AnnotationRequest",  "CONCERNS",            "Node",               []),

    # ── Node connectivity (physical pipe graph) ────────────────────────────
    # PIPE is the primary undirected adjacency between Nodes.
    # Use this for topology / path-finding queries.
    # flow_direction on the relationship reflects the PIPE edge direction
    # as encoded in the graphml — prefer LogicalPipeSegment for resolved flow.
    ("Node",               "PIPE",                "Node",               ["edge_label", "flow_direction", "source"]),

    # ── Endpoint bindings ──────────────────────────────────────────────────
    # endpoint_type is NOT present in the live DB (always null when queried).
    # Only 'source' is a real property on ENDPOINT_OF relationships.
    ("Node",               "ENDPOINT_OF",         "LogicalPipeSegment", ["source"]),
    ("PipeSegment",        "ENDPOINT_OF",         "Node",               ["source"]),

    # ── Logical ↔ Physical segment mapping ────────────────────────────────
    ("LogicalPipeSegment", "COVERS",              "PipeSegment",        ["via_node", "source"]),

    # ── Segment adjacency ──────────────────────────────────────────────────
    ("LogicalPipeSegment", "ADJACENT_VIA_NODES",  "LogicalPipeSegment", ["via_nodes", "via_count"]),
    ("PipeSegment",        "ADJACENT_VIA_NODES",  "PipeSegment",        ["via_nodes", "via_count"]),
    ("PipeSegment",        "JOINS_AT",            "PipeSegment",        ["kind", "trace_nodes"]),
    ("PipeSegment",        "CONTAINS",            "Node",               []),

    # ── Flow evidence ──────────────────────────────────────────────────────
    ("Arrow",              "FLOW_EVIDENCE",       "LogicalPipeSegment", ["dx", "dy", "confidence", "cosine_alignment",
                                                                          "low_confidence", "direction_hint",
                                                                          "pixel_direction", "direction_method",
                                                                          "source", "created_at"]),
    ("Evidence",           "ABOUT",               "LogicalPipeSegment", []),

    # ── Annotations ────────────────────────────────────────────────────────
    ("Annotation",         "ANNOTATES",           "LogicalPipeSegment", []),
    ("Annotation",         "ANNOTATES",           "Node",               []),
    ("Annotation",         "ANNOTATES",           "PipeSegment",        []),
    ("Annotation",         "ANNOTATES",           "PID",                []),
    ("Annotation",         "ANNOTATES",           "Annotation",         []),
    ("Annotation",         "SUPPORTED_BY",        "Evidence",           []),

    # ── Corpus & Global Statistics ─────────────────────────────────────────
    ("SkidCorpus",         "CORPUS_OF",           "Skid",               []),
    ("GlobalStatistic",    "STATISTICS_OF",        "Plant",              []),
    ("GlobalStatisticsSummary", "SUMMARY_OF",      "Plant",              []),
]

# Flat set of valid relationship types
REL_TYPES = {r[1] for r in RELATIONSHIPS}

# Relationship type → property keys (first occurrence wins)
REL_PROPERTIES: Dict[str, List[str]] = {}
for _from, _rel, _to, _props in RELATIONSHIPS:
    if _rel not in REL_PROPERTIES:
        REL_PROPERTIES[_rel] = _props


# ---------------------------------------------------------------------------
# Capability → intent mapping
# Used by IntentConfirmer to route natural-language questions to the right
# sub-graph and the right query pattern.
# ---------------------------------------------------------------------------

CAPABILITY_MAP = {

    "engineering_inventory": {
        "description": "Equipment symbol counts and classification by type.",
        "example_questions": [
            # Count queries
            "How many valves are on this PID?",
            "How many tanks?",
            "How many pumps?",
            "Count symbols by type.",
            "How many equipment symbols?",
            "How many arrows?",
            "How many check valves?",
            "How many inline equipment symbols?",
            # "Show all" / "list all" patterns
            "Show all valves.",
            "List all valves.",
            "List all valves on this drawing.",
            "Show all tanks.",
            "List all tanks.",
            "Show all tanks on this drawing.",
            "Show all pumps.",
            "List all pumps.",
            "Show all instrumentation.",
            "List all instrumentation symbols.",
            "Show all instruments.",
            "Show all equipment.",
            "Show all equipment symbols.",
            "List all symbols.",
            "Show all arrows.",
            "List all arrows.",
            # Safety / inferred equipment
            "Show all check valves.",
            "List all check valves.",
            "Show all inline equipment.",
            "List all inline equipment.",
            "Show all pumps on this drawing.",
            # Generic equipment queries
            "What equipment is on this drawing?",
            "List equipment types.",
        ],
        "primary_node": "Node",
        "filter": "n.structural_type = 'SYMBOL' AND n.label IN ['tank','valve','instrumentation','general','inlet/outlet','arrow','crossing']",
        "warnings": [
            "NEVER use label='pump' — pumps are label='tank' WITH functional_label='pump'. Always use BOTH conditions.",
            "background nodes are NEVER loaded into Neo4j — always exclude with n.label <> 'background'.",
            "arrow and crossing nodes are structural — exclude them from equipment inventory with NOT n.label IN ['arrow','crossing','background'].",
            "connector nodes (structural_type='CONNECTOR') are pipe path intermediates, not equipment — exclude with structural_type='SYMBOL'.",
            "inferred_check_valve and inferred_inline_equipment are valid label values from Phase 1.",
        ],
        "example_cypher": (
            "MATCH (p:PID {pid_id:$pid_id})-[:CONTAINS]->(n:Node) "
            "WHERE n.structural_type = 'SYMBOL' AND n.label <> 'background' "
            "RETURN n.label AS symbol_type, count(n) AS total ORDER BY total DESC"
        ),
    },

    "valve_placement": {
        "description": "Valve enumeration, placement context, and pipe connectivity.",
        "example_questions": [
            # Location/placement queries
            "Which valves are upstream of the tank?",
            "Which valves are downstream of the pump?",
            "Show valves between two points.",
            # Connection queries
            "List all valves with their connected segments.",
            "Show valves connected to pumps.",
            "Which valves connect to tanks?",
            # Check valve queries
            "Show all check valves.",
            "Where are check valves located?",
            "How many check valves are there?",
            "What types of valves are on this drawing?",
            "Show valve type breakdown.",
            "Which valves connect to tanks?",
            # "Show all" / "list all" patterns
            "Show all valves.",
            "List all valves.",
            "Show all valves on this drawing.",
            # Count queries
            "How many valves?",
            "How many valves are there?",
            "Count valves.",
            # Specific valve queries
            "Where is valve V-101?",
            "Show valve locations.",
            "List valve connections.",
        ],
        "primary_node": "Node",
        "filter": "n.label = 'valve'",
        "warnings": [
            "A valve connected to a tank or instrument via 1 PIPE hop will return zero rows — all connections go through connector intermediates. Use PIPE*1..20 for multi-hop traversal.",
            "check valves use label='inferred_check_valve', NOT label='valve'. Always query both when asking about all valves.",
            "Degree formula: size([(n)-[:PIPE]-(m:Node)|m]) AS degree. Do NOT use size((n)-[:PIPE]-()) after a WITH clause.",
        ],
        "example_cypher": (
            "MATCH (p:PID {pid_id:$pid_id})-[:CONTAINS]->(v:Node {label:'valve'}) "
            "OPTIONAL MATCH (v)-[:PIPE]-(neighbour:Node) "
            "RETURN v.id AS valve_id, collect(DISTINCT neighbour.id) AS neighbours LIMIT 50"
        ),
    },

    "instrument_attachment": {
        "description": "Instrument presence, type breakdown, and pipe/equipment attachment.",
        "example_questions": [
            # Attachment queries
            "How many instruments are attached to pipe segments?",
            "Which instruments are attached to equipment?",
            "Show instruments attached to tanks.",
            # Orphan/missing queries
            "Are there any orphan instruments?",
            "Which instruments have no attachment?",
            "Show unattached instruments.",
            # "Show all" / "list all" patterns
            "Show all instruments.",
            "List all instruments.",
            "Show all instrumentation.",
            "List all instrumentation on this drawing.",
            # Count queries
            "How many instruments?",
            "How many instruments are there?",
            "Count all instrumentation.",
            # Type breakdown
            "List instruments by type.",
            "What types of instruments are on this drawing?",
            "Show instrument breakdown.",
        ],
        "primary_node": "Node",
        "filter": "n.label = 'instrumentation'",
        "warnings": [
            "Instruments connect to pipe segments via CONTAINS, not directly. To find instrument's LPS: MATCH (n:Node {label:'instrumentation'})<-[:CONTAINS]-(ps:PipeSegment)<-[:COVERS]-(lps:LogicalPipeSegment).",
            "Orphaned instruments: use pre-computed Annotation type='orphan_node' — do NOT recompute by checking degree.",
        ],
        "example_cypher": (
            "MATCH (p:PID {pid_id:$pid_id})-[:CONTAINS]->(n:Node {label:'instrumentation'}) "
            "OPTIONAL MATCH (ps:PipeSegment)-[:CONTAINS]->(n) "
            "RETURN n.id AS instrument_id, ps.id AS pipe_segment LIMIT 50"
        ),
    },

    "engineering_correctness": {
        "description": (
            "Topology-based P&ID engineering conformance checks. "
            "Heuristic checks using label, connectivity, and flow direction only. "
            "Results require engineer review. "
            "Distinct from drawing_consistency (pre-computed structural defects) "
            "and isolation_reachability (graph component separation). "
            "When the user asks about 'violations' or 'rule violations', query the "
            "pre-computed Annotation nodes with type='engineering_rule_violation' "
            "instead of recomputing topology checks."
        ),
        "example_questions": [
            "Are all tanks instrumented?",
            "Which tanks have no instruments?",
            "Do all pumps have isolation valves?",
            "Are all tanks isolatable?",
            "Is every pump isolatable?",
            "Which valves have bypass paths?",
            "Are there any unisolated tanks?",
            "Show engineering correctness summary.",
            "Run engineering checks.",
            "Which tanks are unmonitored?",
            "Do all tanks have instruments?",
            "Are all boundary interfaces correctly connected?",
            "Are there any engineering rule violations?",
            "Show rule violations.",
            # Safety equipment / HAZOP-style queries
            "Is there reverse flow protection?",
            "Which equipment has no check valve?",
            "Show missing check valve violations.",
            "Show missing isolation valve violations.",
            "Show missing suction strainer violations.",
            "Show critical severity violations.",
            "Show high severity violations.",
            "Are there any missing suction strainers?",
        ],
        "primary_node": "Node",
        "note": (
            "PUMP CRITICAL: There is NO label='pump' in the graph. "
            "Pump units appear as label='tank' with functional_label='pump'. "
            "Use coalesce(t.functional_label, t.label) to distinguish pumps from vessels. "
            "Do NOT rely on bbox size to classify pumps vs vessels. "
            "For 'violations'/'rule violations' questions, use: "
            "MATCH (a:Annotation) WHERE a.type = 'engineering_rule_violation' "
            "AND a.pid_id = $pid_id RETURN a.id, a.pattern_type, a.severity, "
            "a.explanation, a.target_id LIMIT 50. "
            "Violation pattern_type values: 'missing_check_valve' (CRITICAL), "
            "'missing_isolation_valve' (HIGH), 'missing_suction_strainer' (MEDIUM). "
            "Check valve nodes: label='inferred_check_valve' (33 across PIDs)."
        ),
        "warnings": [
            "PUMP queries: always use n.label = 'tank' AND n.functional_label = 'pump'. Omitting functional_label returns ALL tanks.",
            "'Isolatable' means reachable from a valve via PIPE*1..20 — not a single hop.",
            "Pre-computed violations exist as Annotation type='engineering_rule_violation' — prefer querying those over recomputing topology.",
            "missing_check_valve, missing_isolation_valve, missing_suction_strainer are the only confirmed violation pattern_type values.",
        ],
        "sub_intents": {
            "violations":             "Pre-computed engineering rule violations (Annotation type='engineering_rule_violation')",
            "violation_check_valve":  "Violations filtered to pattern_type='missing_check_valve'",
            "violation_isolation":    "Violations filtered to pattern_type='missing_isolation_valve'",
            "violation_strainer":     "Violations filtered to pattern_type='missing_suction_strainer'",
            "reverse_flow_protection":"Check valve coverage — equipment missing reverse flow protection",
            "suction_strainer":       "Suction strainer coverage — pumps missing strainer",
            "instrument_coverage":    "Tanks/pumps with no instrumentation within 5 PIPE hops",
            "valve_isolation":        "Tanks/pumps that cannot reach any valve within 8 PIPE hops",
            "bypass_existence":       "Valves with degree >= 3 (potential bypass junctions)",
            "boundary_integrity":     "inlet/outlet nodes with degree != 1",
            "default":                "Full correctness summary across all checks",
        },
        "example_cypher": (
            "MATCH (a:Annotation) WHERE a.type = 'engineering_rule_violation' "
            "AND a.pid_id = $pid_id "
            "RETURN a.id AS violation_id, a.pattern_type AS rule_name, "
            "a.severity AS severity, a.explanation AS explanation, "
            "a.target_id AS affected_equipment "
            "ORDER BY CASE a.severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' "
            "THEN 2 ELSE 3 END LIMIT 50"
        ),
    },

    "line_attributes": {
        "description": (
            "Pipe segment attributes at BOTH physical and logical levels. "
            "Use PipeSegment for raw geometry queries (node_count, component_id, geometry_hash, JOINS_AT). "
            "Use LogicalPipeSegment for route-level queries (flow_state, flow_direction, "
            "flow_confidence, phase4_hint, ADJACENT_VIA_NODES, COVERS). "
            "COVERS direction: (lps:LogicalPipeSegment)-[:COVERS]->(ps:PipeSegment) — never reverse."
        ),
        "example_questions": [
            # Physical segment queries
            "List pipe segments with more than 5 nodes.",
            "Which segments share the same component_id?",
            "Show adjacent pipe segments.",
            "Where do pipe segments join?",
            # Logical pipe segment queries
            "How many logical pipe segments are there?",
            "How many pipe lines?",
            "How many LPS?",
            "List all pipe lines.",
            "Show all logical segments.",
            # Flow state queries
            "How many LPS have SEEDED flow state?",
            "How many pipe lines have SEEDED flow?",
            "How many LPS have UNKNOWN flow state?",
            "How many pipe lines have UNKNOWN flow?",
            "How many LPS have PROPAGATED flow?",
            "Show all LPS with FORWARD flow direction.",
            "Show pipe lines with REVERSE flow.",
            "List segments with UNKNOWN flow state.",
            # Flow confidence queries
            "Show LPS with flow confidence below 0.5.",
            "Which pipe lines have low confidence?",
            "List uncertain flow segments.",
            # Adjacency queries
            "Show the LPS adjacency graph.",
            "Which pipe lines are adjacent?",
            "Show adjacent logical segments.",
            # Phase4 hint queries
            "How many LPS have phase4_hint='direction_evidence_missing'?",
            "Show segments with evidence missing.",
            "What is the flow state breakdown across all LPS?",
            "List pipe lines by flow state.",
            # Generic list/show queries
            "Show all pipe segments.",
            "List all pipe lines.",
            "Show all LPS.",
        ],
        "primary_node": "PipeSegment",
        "secondary_node": "LogicalPipeSegment",
        "warnings": [
            "COVERS direction is ALWAYS (lps:LogicalPipeSegment)-[:COVERS]->(ps:PipeSegment). NEVER reverse this.",
            "flow_direction is NULL when flow_state is UNKNOWN, BLOCKED, or SEEDED_UNKNOWN. Always check flow_state first.",
            "NEVER filter WHERE lps.flow_direction = 'UNKNOWN' — that string value does not exist; use WHERE lps.flow_state = 'UNKNOWN' instead.",
            "LPS.id format is 'node1__node2'. STARTS WITH 'valve94__' means valve94 is the natural-first endpoint; flow direction FORWARD means flow goes valve94 → node2.",
            "ADJACENT_VIA_NODES exists on LogicalPipeSegment (not PipeSegment). via_nodes (LIST) and via_count (INT) are its properties.",
        ],
        "ps_properties": [
            "id",               # "PS_1", "PS_57"
            "pid_id",
            "segment_status",   # "NORMAL" — only confirmed value
            "node_count",       # INTEGER — number of nodes in this physical segment
            "component_id",     # INTEGER — 0=main network, >0=isolated subgraph
            "geometry_hash",    # STRING MD5 fingerprint for duplicate detection
            "source",           # "derived"
        ],
        "lps_properties": [
            "id",               # "{node1}__{node2}" e.g. "arrow102__crossing151"
            "pid_id",
            "flow_state",       # "SEEDED" | "PROPAGATED" | "UNKNOWN"
            "flow_direction",   # "FORWARD" | "REVERSE" — null when flow_state="UNKNOWN"
            "flow_confidence",  # FLOAT 0.0–1.0
            "seed_confidence",  # FLOAT — confidence of seeding arrow
            "flow_source",      # "evidence" | "propagated" | "none" | "propagation_blocked"
            "phase4_hint",      # propagation directive: "direction_evidence_missing" |
                                # "lps_low_confidence_evidence" | "terminate_propagation" | etc.
        ],
        "lps_relationships": {
            "COVERS":             "(lps)-[:COVERS]->(ps:PipeSegment)  — never reverse",
            "ADJACENT_VIA_NODES": "(lps)-[:ADJACENT_VIA_NODES]->(lps2)  via_nodes: LIST, via_count: INT",
            "FLOW_EVIDENCE":      "(arrow:Arrow)-[:FLOW_EVIDENCE]->(lps)  confidence, direction_hint, pixel_direction, direction_method",
            "ENDPOINT_OF":        "(node:Node)-[:ENDPOINT_OF]->(lps)  endpoint_type, source",
        },
        "example_cypher": (
            "MATCH (ps:PipeSegment {pid_id:$pid_id}) "
            "RETURN ps.id, ps.node_count, ps.component_id, ps.segment_status "
            "ORDER BY ps.node_count DESC LIMIT 50"
        ),
        "lps_example_cypher": (
            "MATCH (lps:LogicalPipeSegment {pid_id:$pid_id}) "
            "RETURN lps.id, lps.flow_state, lps.flow_direction, lps.flow_confidence "
            "ORDER BY lps.flow_confidence ASC NULLS LAST LIMIT 50"
        ),
        "lps_count_by_state_cypher": (
            "MATCH (lps:LogicalPipeSegment {pid_id:$pid_id}) "
            "RETURN lps.flow_state AS flow_state, count(lps) AS pipe_lines "
            "ORDER BY pipe_lines DESC"
        ),
        "lps_adjacency_cypher": (
            "MATCH (a:LogicalPipeSegment {pid_id:$pid_id})"
            "-[r:ADJACENT_VIA_NODES]->(b:LogicalPipeSegment) "
            "RETURN a.id AS lps_a, b.id AS lps_b, r.via_nodes, r.via_count LIMIT 50"
        ),
        "lps_phase4_hint_cypher": (
            "MATCH (lps:LogicalPipeSegment {pid_id:$pid_id}) "
            "WHERE lps.phase4_hint IS NOT NULL "
            "RETURN lps.phase4_hint AS hint, count(lps) AS n ORDER BY n DESC"
        ),
    },

    "connectivity_topology": {
        "description": (
            "Graph traversal — adjacency, upstream/downstream paths, reachability, "
            "and PIPE edge-level properties. "
            "PIPE is the correct relationship for Node-level traversal (replaces CONNECTED)."
        ),
        "example_questions": [
            # Reachability queries
            "What is downstream of valve94?",
            "What is upstream of tank12?",
            "Find all nodes reachable from tank12.",
            "Show everything downstream from this valve.",
            # Path queries
            "What is the shortest path between two nodes?",
            "Show path from valve to tank.",
            "Find route between two equipment.",
            # PIPE edge queries
            "How many PIPE edges are there?",
            "How many PIPE connections?",
            "Are all PIPE edges currently UNKNOWN flow direction?",
            "Show all PIPE connections from valve nodes.",
            "List PIPE edges by source.",
            "Show PIPE degree for every SYMBOL node.",
            "Are all PIPE edges sourced from graphml?",
            # Degree queries
            "Show nodes by degree.",
            "Which nodes have degree > 3?",
            "List high-degree nodes.",
            # Connection validation
            "Are all symbols connected?",
            "Is everything connected?",
            "Show disconnected nodes.",
            # Generic topology
            "Show the pipe network.",
            "List all connections.",
            "What's the network topology?",
        ],
        "primary_rel": "PIPE",
        "note": (
            "PIPE is stored as directed in the graphml but should be traversed "
            "in BOTH directions for undirected topology queries. "
            "For resolved flow direction use LogicalPipeSegment.flow_direction."
        ),
        "warnings": [
            "Symbol-to-symbol connectivity: NEVER use a single PIPE hop. Equipment connects via connector intermediates. Use PIPE*1..20.",
            "Degree: use size([(n)-[:PIPE]-(m:Node)|m]) AS deg. Do NOT use size((n)-[:PIPE]-()) after a WITH clause.",
            "upstream/downstream traversal: use ENDPOINT_OF → LogicalPipeSegment → ADJACENT_VIA_NODES, not raw PIPE traversal.",
            "crossing and arrow nodes appear in PIPE paths — filter them out with NOT n.label IN ['crossing','arrow'] in path results.",
        ],
        "pipe_edge_properties": {
            "description": (
                "Every PIPE relationship carries these properties. "
                "Use for PIPE edge validation queries ('are all PIPE edges UNKNOWN?', "
                "'how many PIPE edges?', 'show PIPE connections from valve nodes')."
            ),
            "properties": {
                "flow_direction": "always 'UNKNOWN' — direction is resolved at LPS level only",
                "source":         "always 'graphml'",
                "edge_label":     "always 'solid'",
                "pid_id":         "STRING — scoping field, present on every PIPE edge",
            },
            "total_count": "923 PIPE relationships across both PIDs (~490 per PID)",
            "degree_formula": "size([(n)-[:PIPE]-(m:Node)|m]) AS degree",
            "validation_cypher": (
                "MATCH ()-[r:PIPE {pid_id:$pid_id}]->() "
                "WHERE r.flow_direction <> 'UNKNOWN' "
                "RETURN count(*) AS non_unknown  -- expect 0"
            ),
            "count_cypher": (
                "MATCH ()-[r:PIPE]->() WHERE r.pid_id = $pid_id "
                "RETURN count(r) AS pipe_edge_count"
            ),
            "symbol_connections_cypher": (
                "MATCH (v:Node {label:'valve', pid_id:$pid_id})-[r:PIPE]-(n:Node) "
                "RETURN v.id, n.id, n.label ORDER BY v.id LIMIT 50"
            ),
        },
        "example_cypher": (
            "MATCH path = (start:Node {id:$start_id})-[:PIPE*1..5]-(end:Node) "
            "WHERE end.label <> 'background' "
            "RETURN [n IN nodes(path) | n.id] AS path_nodes LIMIT 20"
        ),
        "upstream_downstream_cypher": (
            "// Use ENDPOINT_OF → LogicalPipeSegment → ADJACENT_VIA_NODES for multi-hop directional queries.\n"
            "// Example: What is downstream of valve94 on $pid_id?\n"
            "// IMPORTANT: flow_direction is relative to each LPS segment name (node1__node2).\n"
            "// FORWARD = flow goes node1→node2.  REVERSE = flow goes node2→node1.\n"
            "// To find segments where 'valve94' is the UPSTREAM end (flow exits it):\n"
            "//   FORWARD + lps.id STARTS WITH 'valve94__'  (valve94 is node1, flow exits to other)\n"
            "//   REVERSE + lps.id ENDS WITH   '__valve94'  (valve94 is node2, REVERSE means valve94→node1)\n"
            "MATCH (start:Node)-[:ENDPOINT_OF]->(lps0:LogicalPipeSegment)\n"
            "WHERE (start.id = 'valve94' OR start.equipment_id = 'valve94')\n"
            "  AND start.pid_id = $pid_id\n"
            "  AND lps0.flow_state IN ['SEEDED','PROPAGATED']\n"
            "  AND (\n"
            "    (lps0.flow_direction = 'FORWARD' AND lps0.id STARTS WITH 'valve94__')\n"
            "    OR\n"
            "    (lps0.flow_direction = 'REVERSE' AND lps0.id ENDS WITH '__valve94')\n"
            "  )\n"
            "MATCH (lps0)-[:ADJACENT_VIA_NODES*0..8]-(lps:LogicalPipeSegment)\n"
            "WHERE lps.flow_state IN ['SEEDED','PROPAGATED']\n"
            "MATCH (far:Node)-[:ENDPOINT_OF]->(lps)\n"
            "WHERE far.id <> start.id\n"
            "  AND far.structural_type = 'SYMBOL'\n"
            "  AND NOT far.label IN ['crossing','arrow']\n"
            "RETURN DISTINCT far.id AS node_id, far.label AS type,\n"
            "       lps.id AS via_segment, lps.flow_confidence AS confidence\n"
            "ORDER BY far.label, far.id\n"
            "LIMIT 50\n"
            "// For upstream (what feeds into valve94), swap STARTS WITH / ENDS WITH.\n"
            "// ADJACENT_VIA_NODES*0..8 traverses up to 8 pipe-line hops.\n"
            "// Always filter out crossing and arrow nodes — they are structural artifacts."
        ),
    },

    "flow_direction": {
        "description": (
            "As-drawn flow direction resolved from Arrow evidence and LogicalPipeSegment. "
            "Flow direction exists at TWO levels: "
            "(1) LPS level — LogicalPipeSegment.flow_direction/state/confidence — the primary source. "
            "(2) Node level — denormalised onto individual Node records from the LPS pipeline. "
            "Use LPS-level queries for pipe-line questions. "
            "Use Node-level queries when the question asks about a specific symbol type "
            "(valve, tank, instrumentation) having a flow direction."
        ),
        "example_questions": [
            # Segment-level flow queries
            "What is the flow direction on segment LPS_42?",
            "Which segments have unknown flow direction?",
            "Which pipe lines have no flow direction?",
            "Show segments with SEEDED flow.",
            "Show segments with PROPAGATED flow.",
            "List pipe lines with UNKNOWN flow.",
            # Arrow queries
            "Show all arrows and their confidence scores.",
            "How many arrows are there?",
            "List all flow arrows.",
            "Show arrow locations.",
            # Equipment-level flow queries
            "Show all valves with resolved flow direction.",
            "Which valves have flow direction?",
            "Which tanks have SEEDED flow state?",
            "Show SYMBOL nodes with PROPAGATED flow state.",
            "Which valve nodes have flow confidence below 0.5?",
            "List equipment with uncertain flow.",
            # Flow confidence queries
            "Which pipe lines have low flow confidence?",
            "Show segments with confidence below 0.5.",
            "List uncertain flow directions.",
            # Generic flow queries
            "Show all flow directions.",
            "List flow indicators.",
            "What's the flow direction on this drawing?",
            "Show flow coverage.",
        ],
        "primary_node": "LogicalPipeSegment",
        "evidence_pattern": "(Arrow)-[:FLOW_EVIDENCE]->(LogicalPipeSegment)<-[:ABOUT]-(Evidence)",
        "warnings": [
            "Always check lps.flow_state before using lps.flow_direction.",
            "flow_state='UNKNOWN', 'BLOCKED', or 'SEEDED_UNKNOWN' means flow_direction IS NULL — the property is absent.",
            "flow_state='SEEDED' or 'PROPAGATED' means flow_direction = 'FORWARD' or 'REVERSE'.",
            "NEVER filter WHERE flow_direction = 'UNKNOWN' — 'UNKNOWN' is not a valid direction value.",
            "Prefer Evidence.observed_direction over Evidence.direction as the canonical resolved value.",
            "Node.flow_state has NO 'UNKNOWN' value — only SEEDED or PROPAGATED.",
            "Only SYMBOL nodes with resolved flow carry Node.flow_direction — not all nodes.",
        ],
        "node_level_flow": {
            "description": (
                "Individual Node records carry denormalised flow properties resolved from the "
                "LPS pipeline. Use these for symbol-level flow queries (valves, tanks, instruments) "
                "without traversing the LPS chain."
            ),
            "properties": {
                "flow_direction":  "FORWARD | REVERSE (null if unresolved)",
                "flow_state":      "SEEDED | PROPAGATED — no UNKNOWN on Node",
                "flow_confidence": "FLOAT 0.0–1.0",
                "flow_source":     "always 'phase4_equipment_assignment' on confirmed nodes",
            },
            "example_cypher": (
                "MATCH (n:Node {pid_id:$pid_id}) "
                "WHERE n.flow_direction IS NOT NULL AND n.label = 'valve' "
                "RETURN n.id, n.label, n.flow_direction, n.flow_state, n.flow_confidence "
                "ORDER BY n.flow_confidence ASC LIMIT 50"
            ),
            "count_example_cypher": (
                "MATCH (n:Node {pid_id:$pid_id, structural_type:'SYMBOL'}) "
                "WHERE n.flow_direction IS NOT NULL "
                "RETURN count(n) AS resolved_symbol_count"
            ),
        },
        "example_cypher": (
            "MATCH (lps:LogicalPipeSegment {pid_id:$pid_id}) "
            "WHERE lps.flow_state IN ['SEEDED','PROPAGATED'] "
            "RETURN lps.id, lps.flow_direction, lps.flow_confidence "
            "ORDER BY lps.flow_confidence ASC LIMIT 50"
        ),
    },

    "external_interfaces": {
        "description": "External system connections at the drawing boundary (inlet/outlet nodes). Inlet/outlet pennant shapes are analyzed for flow direction (R7) and contribute Evidence nodes with source='phase3_boundary_semantics'.",
        "example_questions": [
            # Count queries
            "How many external inlets/outlets are there?",
            "How many interfaces?",
            "How many external interfaces?",
            "How many inlets?",
            "How many outlets?",
            "Count boundary connections.",
            # Location queries
            "Which external interfaces are on the left boundary?",
            "Which interfaces are on the right side?",
            # "Show all" / "what" / "list" patterns
            "Show all external interfaces.",
            "List all external interfaces.",
            "List all inlet/outlet nodes.",
            "What external interfaces does this drawing have?",
            "What are the external interfaces?",
            "Show all inlets.",
            "Show all outlets.",
            "List all boundary connections.",
            "Show all boundary interfaces.",
            "List all drawing boundaries.",
        ],
        "primary_node": "Node",
        "filter": "n.label = 'inlet/outlet'",
        "warnings": [
            "structural_type='BOUNDARY' means background noise — NOT interfaces.",
            "External interfaces use label='inlet/outlet' with structural_type='SYMBOL'.",
            "inlet/outlet nodes always connect via exactly one CONNECTOR intermediate.",
        ],
        "side_detection": "n.xmin < 500 → LEFT boundary; n.xmin > 1500 → RIGHT boundary",
        "example_cypher": (
            "MATCH (p:PID {pid_id:$pid_id})-[:CONTAINS]->(n:Node {label:'inlet/outlet'}) "
            "OPTIONAL MATCH (n)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment) "
            "OPTIONAL MATCH (lps)<-[:ABOUT]-(e:Evidence {pid_id:$pid_id, source:'phase3_boundary_semantics'}) "
            "RETURN n.id, n.xmin, n.ymin, "
            "CASE WHEN n.xmin < 500 THEN 'LEFT' WHEN n.xmin > 1500 THEN 'RIGHT' ELSE 'OTHER' END AS side, "
            "lps.id AS lps_id, lps.flow_direction AS flow_direction, lps.flow_state AS flow_state, "
            "e.observed_direction AS boundary_direction, e.confidence AS boundary_confidence, "
            "e.direction_method AS direction_method "
            "LIMIT 50"
        ),
    },

    "redundancy_patterns": {
        "description": "Structural duplicates, identical neighborhoods, rare motifs, and rarity scoring.",
        "example_questions": [
            # Duplicate queries
            "Are there any duplicate symbols?",
            "Show duplicate equipment.",
            "List duplicate nodes.",
            "Which symbols are duplicated?",
            # Geometry-based duplicates
            "Which pipe segments have identical geometry hashes?",
            "Show identical pipe runs.",
            "List segments with same geometry.",
            # Rarity queries
            "Show rare structural motifs.",
            "Which patterns are rare?",
            "List uncommon configurations.",
            "How many structural pattern frequency annotations exist?",
            "Show patterns labelled as architecturally rare.",
            "Show dominant patterns.",
            "Show the rarity label distribution.",
            # Neighborhood queries
            "Which nodes have the rarest local neighbourhood pattern?",
            "Show rare local motifs.",
            # Motif chains
            "Are there any motif chains?",
            "Show pattern chains.",
            # Generic redundancy
            "Show all redundant patterns.",
            "List all duplicates.",
            "What patterns repeat?",
        ],
        "annotation_types": [
            "structural_pattern_frequency",  # how often a node-neighbourhood appears
            "structural_pattern_rarity",     # rarity classification of a pattern
            "rare_motif_local",              # individual rare local motif on a node
        ],
        "rarity_label_values": [
            "dominant",             # most frequent pattern in the corpus
            "common",               # high frequency
            "typical",              # average frequency
            "uncommon",             # below average
            "architecturally_rare", # very rare — may indicate design intent or error
            "priority",             # flagged for engineer review
            "backlog",              # lower urgency
            "tolerable",            # acceptable rarity level
        ],
        "key_properties": {
            "rarity_score":      "FLOAT 0.0–1.0 — higher = more common/dominant",
            "rarity_label":      "STRING — human-readable bucket (see rarity_label_values)",
            "absolute_count":    "INTEGER — raw occurrence count across corpus",
            "normalized_ratio":  "FLOAT — frequency relative to corpus",
            "motif_chain_count": "INTEGER — chained rare motif sequence length (>0 = chain exists)",
            "pattern_type":      "STRING — structural pattern identifier",
            "corpus_normalized": "BOOLEAN — whether counts are normalised to full corpus",
        },
        "via_annotation": "Annotation.type IN ['rare_motif_local','structural_pattern_rarity','structural_pattern_frequency']",
        "warnings": [
            "PipeSegment, NOT Node, has geometry_hash. Use MATCH (ps:PipeSegment) for geometry duplicate checks.",
            "rare_motif_local and structural_pattern_rarity are the correct annotation types — NOT duplicate_symbol_candidate (does not exist).",
            "rarity_score closer to 1.0 = more COMMON/DOMINANT; closer to 0.0 = more RARE.",
        ],
        "direct_check": "PipeSegment geometry_hash comparison",
        "example_cypher": (
            "MATCH (a:Annotation {pid_id:$pid_id}) "
            "WHERE a.type IN ['rare_motif_local','structural_pattern_rarity','structural_pattern_frequency'] "
            "OPTIONAL MATCH (a)-[:ANNOTATES]->(target) "
            "RETURN a.type, a.rarity_score, a.rarity_label, a.absolute_count, target.id AS target_id "
            "ORDER BY a.rarity_score DESC LIMIT 50"
        ),
        "rarity_label_breakdown_cypher": (
            "MATCH (ann:Annotation {pid_id:$pid_id}) "
            "WHERE ann.rarity_label IS NOT NULL "
            "RETURN ann.rarity_label, count(*) AS n ORDER BY n DESC"
        ),
        "architecturally_rare_cypher": (
            "MATCH (ann:Annotation {pid_id:$pid_id})-[:ANNOTATES]->(n:Node) "
            "WHERE ann.rarity_label IN ['architecturally_rare','uncommon'] "
            "AND ann.type = 'rare_motif_local' "
            "RETURN n.id, n.label, ann.rarity_score ORDER BY ann.rarity_score DESC LIMIT 50"
        ),
    },

    "isolation_reachability": {
        "description": "Reachability analysis, isolated nodes, articulation points.",
        "example_questions": [
            # Orphan/isolated queries
            "Which nodes are isolated (orphaned)?",
            "Show isolated symbols.",
            "List orphan nodes.",
            "Are there any isolated equipment?",
            "Show disconnected symbols.",
            # Reachability queries
            "Can node X reach node Y through the pipe network?",
            "Is this valve reachable from the tank?",
            "What can be reached from this point?",
            "Show reachability from valve.",
            # Component queries
            "How many isolated components?",
            "Show isolated sections.",
            "List disconnected components.",
            "Which nodes are in isolated islands?",
            # Generic isolation
            "Show all isolated nodes.",
            "List all orphans.",
            "What's disconnected?",
        ],
        "traversal": "(Node)-[:PIPE*]-(Node)",
        "precomputed": "Annotation.type = 'orphan_node'",
        "warnings": [
            "NEVER check isolation by testing direct PIPE connections between SYMBOL nodes. "
            "Equipment symbols (valve, tank, instrument, etc.) connect to the pipe network VIA "
            "connector nodes, NOT directly to each other. A valve with no direct PIPE connection "
            "to another valve is NOT isolated — it is connected through connectors. "
            "The ONLY correct way to find isolated symbols is via pre-computed Annotation nodes: "
            "MATCH (a:Annotation {pid_id:$pid_id, type:'orphan_node'})-[:ANNOTATES]->(n:Node). "
            "Always exclude arrow, crossing, and background nodes from results.",
        ],
        "via_annotation": "Annotation.type = 'orphan_node' (pre-computed by Phase 3 — do NOT recompute)",
        "example_cypher": (
            "MATCH (a:Annotation {pid_id:$pid_id, type:'orphan_node'})-[:ANNOTATES]->(n:Node) "
            "WHERE NOT n.label IN ['arrow', 'crossing', 'background'] "
            "RETURN n.id AS orphan_node_id, n.label AS type "
            "ORDER BY n.label LIMIT 50"
        ),
    },

    "drawing_consistency": {
        "description": (
            "Pre-computed structural drawing defects via Annotation nodes. "
            "NEVER recompute checks from scratch — always query Annotation.type. "
            "ONLY reports genuine drawing problems, NOT algorithm coverage metrics. "
            "Flow direction gaps are NOT drawing defects — use flow_coverage for those."
        ),
        "example_questions": [
            # Quality/defect checks
            "Are there any drawing quality issues?",
            "Is this diagram structurally consistent?",
            "Are there any orphaned symbols?",
            "Which pipe runs have no associated pipe line?",
            "Give me a full structural anomaly report.",
            "Show all drawing defects.",
            # Structural inventory mode — "show all X" patterns
            "Show all T-junction nodes.",
            "List all T-junctions.",
            "Show all pipe junction nodes.",
            "List all pipe junctions.",
            "Show all structural branch nodes.",
            "List all crossing nodes.",
            "Show all crossings.",
            "Show all high-degree nodes.",
            "Show all manifold nodes.",
            "List all manifolds.",
            "Show all endpoint collision nodes.",
            "List all dead-end segments.",
            "Show all dead ends.",
            # Count queries
            "How many T-junction annotations exist?",
            "How many T-junctions?",
            "How many pipe junctions are there?",
            "How many crossing points?",
            "How many crossings?",
            "Count all manifolds.",
            "How many high-degree nodes?",
            "How many dead-end segments?",
            "How many orphan nodes?",
        ],
        "query_modes": {
            "consistency_check": (
                "Use when the question asks about drawing quality, defects, or consistency. "
                "Query ONLY annotation_types_for_quality: orphan_node, "
                "pipe_segment_no_logical_mapping, endpoint_collision."
            ),
            "structural_inventory": (
                "Use when the engineer explicitly asks for a SPECIFIC structural annotation "
                "type by name (e.g. 'how many T-junctions?', 'show structural_high_degree nodes', "
                "'give me a full structural anomaly report'). "
                "In this mode query annotation_types_structural by the requested type(s). "
                "These are NOT defects — they are normal P&ID topology features."
            ),
        },
        "primary_node": "Annotation",
        "annotation_types_for_quality": [
            # GENUINE DRAWING DEFECTS ONLY — actual problems requiring engineer investigation
            "orphan_node",                      # symbol with zero pipe connections
            "pipe_segment_no_logical_mapping",  # pipe run that could not be grouped into any route
            "endpoint_collision",               # two pipe runs claim the same endpoint
        ],
        "annotation_types_informational": [
            # Report with context, not as failures
            "dead_end_pipe_segment",  # open-ended pipe run — normal for drain/vent/sample lines
        ],
        "annotation_types_structural": [
            # Normal P&ID topology — query when EXPLICITLY requested by type name.
            # Include degree property in RETURN when available.
            "structural_branch",        # 3-way pipe junction (degree=3)
            "structural_t_junction",    # T-junction subtype of branch
            "structural_high_degree",   # node with 4+ pipe connections; ann.degree stores count
            "large_manifold_node",      # unusually high degree (≥10); ann.degree stores count
            "pipe_junction",            # generic pipe junction point
            "pipe_segment_cycle_member",# PipeSegment that is part of a loop/cycle; ann.cycle_length
            "endpoint_collision",       # two pipe ends at same point (also a defect)
        ],
        "annotation_types_flow_coverage": [
            # These belong to the flow_coverage intent, NOT here.
            # Arrow placement is sparse on real P&IDs --- missing arrows are normal.
            # direction_evidence_missing is no longer an Annotation — gaps are
            # tracked directly on lps.phase4_hint and lps.flow_state = 'UNKNOWN'.
            "pipe_segment_no_evidence_via_lps",
            "ps_unreachable_from_evidence",
        ],
        "warnings": [
            "NEVER query drawing_consistency annotation types for flow direction gaps — use lps.flow_state = 'UNKNOWN' instead.",
            "dead_end_pipe_segment is INFORMATIONAL, not a defect — open pipe ends are normal on real P&IDs (drain/vent/sample lines).",
            "pipe_segment_no_evidence_via_lps belongs to flow_coverage intent, NOT drawing_consistency.",
            "structural_branch, structural_t_junction, structural_high_degree are NORMAL topology — not defects. Only report them when engineer explicitly asks.",
            "ANNOTATES direction: always (Annotation)-[:ANNOTATES]->(target). Never reverse.",
        ],
        "warning": (
            "CRITICAL SCOPE: For consistency questions query ONLY orphan_node, "
            "pipe_segment_no_logical_mapping, and endpoint_collision. "
            "dead_end_pipe_segment is informational only — open ends are normal on P&IDs. "
            "NEVER include pipe_segment_no_evidence_via_lps or ps_unreachable_from_evidence — "
            "arrows are sparse on real P&IDs and missing coverage is an analysis "
            "limitation, not a drawing defect. "
            "For missing flow use lps.flow_state = 'UNKNOWN' instead of querying annotations. "
            "T-junctions, branch points, and high-degree nodes are normal topology, never defects "
            "— BUT do query them when the engineer explicitly asks for that type by name."
        ),
        "example_cypher": (
            "MATCH (a:Annotation {pid_id:$pid_id}) "
            "WHERE a.type IN ['orphan_node','pipe_segment_no_logical_mapping','endpoint_collision'] "
            "RETURN a.type AS issue_type, count(a) AS occurrences "
            "ORDER BY occurrences DESC"
        ),
        "structural_inventory_example_cypher": (
            "-- Use this pattern when the engineer asks for a specific structural type, "
            "-- e.g. 'how many T-junctions', 'show all structural_high_degree nodes': "
            "MATCH (ann:Annotation {pid_id:$pid_id, type:'structural_t_junction'})"
            "-[:ANNOTATES]->(n:Node) "
            "RETURN n.id, n.label, ann.degree ORDER BY ann.degree DESC LIMIT 50"
        ),
        "full_structural_report_cypher": (
            "-- Use when engineer asks for a full structural anomaly report: "
            "MATCH (ann:Annotation {pid_id:$pid_id})-[:ANNOTATES]->(t) "
            "WHERE ann.type IN ['orphan_node','dead_end_pipe_segment','structural_branch',"
            "'structural_t_junction','structural_high_degree','large_manifold_node',"
            "'pipe_junction','endpoint_collision','pipe_segment_cycle_member'] "
            "RETURN ann.type, count(*) AS occurrences ORDER BY occurrences DESC"
        ),
    },

    "flow_coverage": {
        "description": (
            "Flow direction analysis coverage summary. "
            "Reports how many pipe lines have a resolved flow direction vs how many "
            "remain unresolved, and the reasons why. "
            "This is an analysis completeness metric, NOT a drawing defect check. "
            "Arrow placement is sparse and implicit on real P&IDs — unresolved pipe lines "
            "are normal and expected, not errors."
        ),
        "example_questions": [
            # Coverage percentage queries
            "What is the flow direction coverage?",
            "What percentage of pipes have flow direction determined?",
            "How complete is the flow analysis?",
            "What's the flow coverage percentage?",
            # Resolved vs unresolved
            "How many pipe lines have a resolved flow direction?",
            "How many pipe lines have resolved flow?",
            "How many are unresolved?",
            "Which pipe lines are missing flow direction?",
            "Which pipes don't have flow direction?",
            "Show unresolved flow segments.",
            # Gap analysis
            "Show flow direction gaps.",
            "Where are the flow gaps?",
            "Which segments have no flow data?",
            # Breakdown queries
            "Show flow state breakdown.",
            "List pipe lines by flow status.",
            "What's the coverage summary?",
            # Generic coverage
            "How complete is the flow data?",
            "What's missing flow direction?",
            "Show flow analysis status.",
        ],
        "primary_node": "LogicalPipeSegment",
        "flow_states": {
            "SEEDED":         "flow confirmed directly from an arrow on the drawing",
            "PROPAGATED":     "flow inferred by tracing from a nearby seeded pipe line",
            "UNKNOWN":        "flow could not be determined — no nearby arrow, normal on real P&IDs",
            "BLOCKED":        "propagation blocked by Phase 3.5 safety engineering rule violation",
            "SEEDED_UNKNOWN": "has arrow evidence but direction is contradictory; flow unresolved",
        },
        "coverage_annotation_types": [
            # direction_evidence_missing is no longer an Annotation node.
            # For missing flow, query lps.flow_state = 'UNKNOWN' directly.
            "lps_low_confidence_evidence",
            "pipe_segment_no_evidence_via_lps",
            "ps_unreachable_from_evidence",
        ],
        "note": (
            "Always frame results as a coverage ratio: "
            "'X of Y pipe lines have resolved flow direction (Z%)'. "
            "Do not frame unresolved lines as errors or failures."
        ),
        "warnings": [
            "Unresolved pipe lines (UNKNOWN flow_state) are NORMAL on real P&IDs — arrows are sparse. Do NOT frame them as errors.",
            "NEVER filter WHERE lps.flow_direction = 'UNKNOWN' — that string value does not exist; use WHERE lps.flow_state = 'UNKNOWN'.",
            "direction_evidence_missing is no longer an Annotation node — check lps.phase4_hint = 'direction_evidence_missing' instead.",
        ],
        "example_cypher": (
            "MATCH (lps:LogicalPipeSegment {pid_id:$pid_id}) "
            "RETURN lps.flow_state AS flow_state, count(lps) AS pipe_lines "
            "ORDER BY pipe_lines DESC"
        ),
    },

    "annotation_requests": {
        "description": (
            "Human- or system-raised annotation requests on specific nodes. "
            "Covers pending reviews, anomaly flags, and HITL tasks. "
            "NOT the same as Annotation nodes — AnnotationRequest is a distinct type "
            "linked from PID via HAS_ANNOTATION and to the flagged Node via CONCERNS."
        ),
        "example_questions": [
            # Pending requests
            "Are there any pending annotation requests?",
            "Show pending requests.",
            "List open requests.",
            "How many pending requests?",
            # Flagged nodes
            "Which nodes have been flagged for review?",
            "Show flagged nodes.",
            "List nodes needing review.",
            # Request type breakdown
            "Show annotation requests by anomaly type.",
            "List requests by type.",
            "What types of requests are there?",
            # Specific anomaly types
            "How many DUPLICATE_BBOX requests are there?",
            "Show DUPLICATE_BBOX requests.",
            "Show all dangling inline annotation requests.",
            "List dangling inline requests.",
            "Show all orphan node annotation requests.",
            "List ORPHAN_NODE requests.",
            # Equipment-specific requests
            "Show annotation requests for valve nodes.",
            "Which valves are flagged?",
            "Show requests for instrumentation.",
            # Target identification
            "Which specific nodes are flagged by annotation requests?",
            "Show nodes with active requests.",
            "List all flagged equipment.",
            # Generic request queries
            "Show all annotation requests.",
            "List all review requests.",
            "What needs review?",
        ],
        "primary_node": "AnnotationRequest",
        "warnings": [
            "AnnotationRequest is DISTINCT from Annotation — they are different node labels.",
            "Path: (PID)-[:HAS_ANNOTATION]->(AnnotationRequest)-[:CONCERNS]->(Node). NOT via ANNOTATES.",
            "Annotation nodes use ANNOTATES. AnnotationRequest nodes use CONCERNS + HAS_ANNOTATION.",
        ],
        "traversal": "(PID)-[:HAS_ANNOTATION]->(AnnotationRequest)-[:CONCERNS]->(Node)",
        "total": 75,  # live count across both PIDs (~35 per PID based on catalogue
        "anomaly_types": {
            "DUPLICATE_BBOX":  (
                "Two nodes share identical bounding box coordinates. "
                "Indicates a graphml parsing or symbol detection duplicate."
            ),
            "ORPHAN_NODE": (
                "Degree-0 symbol with no pipe connections. "
                "The node exists in the graphml but is not connected to any pipe."
            ),
            "DANGLING_INLINE": (
                "Degree-1 inline component expected to have degree≥2. "
                "An instrumentation or general node that should be inline but has only one pipe connection."
            ),
        },
        "properties": {
            "request_id":   "STRING — unique AR ID",
            "pid_id":       "STRING — drawing scope",
            "node_id":      "STRING — ID of the flagged Node",
            "label":        "STRING — Node.label of the flagged node (valve, instrumentation, etc.)",
            "anomaly_type": "STRING — one of DUPLICATE_BBOX | ORPHAN_NODE | DANGLING_INLINE",
            "detail":       "STRING — human-readable description of the issue",
            "status":       "STRING — 'OPEN' (only confirmed value)",
            "source":       "STRING — 'graphml' (phase 0 origin)",
            "phase_origin": "INTEGER — 0 (all current ARs raised during graphml ingestion)",
        },
        "example_cypher": (
            "MATCH (p:PID {pid_id:$pid_id})-[:HAS_ANNOTATION]->(ar:AnnotationRequest) "
            "OPTIONAL MATCH (ar)-[:CONCERNS]->(n:Node) "
            "RETURN ar.request_id, ar.anomaly_type, ar.status, ar.detail, n.id AS node_id "
            "ORDER BY ar.anomaly_type LIMIT 50"
        ),
        "dangling_example_cypher": (
            "MATCH (p:PID {pid_id:$pid_id})-[:HAS_ANNOTATION]->(ar:AnnotationRequest) "
            "WHERE ar.anomaly_type = 'DANGLING_INLINE' "
            "RETURN ar.node_id, ar.label, ar.detail LIMIT 50"
        ),
        "by_label_example_cypher": (
            "MATCH (p:PID {pid_id:$pid_id})-[:HAS_ANNOTATION]->(ar:AnnotationRequest) "
            "WHERE ar.label = 'valve'  -- or 'instrumentation', 'connector', etc. "
            "RETURN ar.request_id, ar.anomaly_type, ar.detail LIMIT 50"
        ),
    },

    "segment_junction_topology": {
        "description": (
            "Junction and adjacency analysis between pipe segments. "
            "JOINS_AT links two PipeSegments at a shared junction node. "
            "JOINS_AT.trace_nodes[1] is always the junction symbol (valve/arrow/tank); "
            "indices 0 and 2 are connector nodes."
        ),
        "example_questions": [
            # Junction connectivity queries
            "Which pipe segments meet at a valve junction?",
            "Which segments meet at this junction?",
            "Show segments joining at node X.",
            "What joins at this point?",
            # Specific segment queries
            "How many junctions does PS_57 have?",
            "Which segments connect to PS_57?",
            "Show junctions for this segment.",
            # Adjacency queries
            "Show adjacency between segments.",
            "List adjacent pipe segments.",
            "Which segments are adjacent?",
            # Branch point queries
            "Where do pipe segments branch?",
            "Show all branch points.",
            "List branching locations.",
            # Junction count
            "How many junctions are there?",
            "How many junction points?",
            "Count all branches.",
            # Generic junction queries
            "Show all junctions.",
            "List junction topology.",
            "Where do segments meet?",
        ],
        "primary_rel": "JOINS_AT",
        "note": "JOINS_AT.trace_nodes[1] = junction symbol. Indices 0 and 2 = connectors.",
        "warnings": [
            "JOINS_AT.trace_nodes[1] is the junction symbol (index 0 and 2 are connector nodes).",
            "JOINS_AT links PipeSegment to PipeSegment, not LogicalPipeSegment.",
        ],
        "example_cypher": (
            "MATCH (ps1:PipeSegment {pid_id:$pid_id})-[j:JOINS_AT]->(ps2:PipeSegment) "
            "RETURN ps1.id AS seg_a, j.kind AS junction_kind, "
            "j.trace_nodes[1] AS junction_symbol, ps2.id AS seg_b LIMIT 50"
        ),
    },

    "cross_domain": {
        "description": (
            "Multi-domain queries that combine two or more node types in a single question. "
            "Examples: valves on segments with unknown flow direction; instruments attached "
            "to pipe segments that have no logical pipe segment mapping; equipment reachable "
            "from a specific inlet. Use the full schema to compose JOIN queries across "
            "Node, LogicalPipeSegment, PipeSegment, Annotation, Arrow, and Evidence. "
            "Also handles: ESV/KAV annotation classification, annotation triage metadata "
            "(hitl_severity, audience, phase4_hint), equipment semantics Evidence nodes, "
            "and PID-level summary statistics."
        ),
        "example_questions": [
            # Multi-domain equipment queries
            "Which valves are on segments with unknown flow direction?",
            "Which valves are on segments with unknown flow?",
            "Show valves on pipe lines without flow.",
            "Which pipe segments contain both a valve and an instrument?",
            "Show segments with valves and instruments.",
            "List pipe lines with instrumentation.",
            # Equipment-segment-annotation queries
            "Show instruments attached to pipe segments without logical mapping.",
            "Which instruments are on unmapped segments?",
            "List instruments on disconnected pipe runs.",
            # Reachability across domains
            "Which tanks are reachable from inlet nodes?",
            "What equipment can be reached from this valve?",
            "Show all nodes reachable from external interfaces.",
            # Annotation triage metadata (ESV, KAV, severity)
            "How many ESV-category annotations are there?",
            "Show all HIGH-severity annotations.",
            "List critical annotations.",
            "What is the total ESV count for this drawing?",
            "What is the KAV breakdown?",
            "Show KAV annotations.",
            # Equipment semantics annotations
            "Show all equipment semantics annotations.",
            "Show Evidence nodes from equipment semantics.",
            "List equipment-related annotations.",
            # Annotation grouping/breakdown
            "Show annotations grouped by intent.",
            "List annotations by intent.",
            "Show annotations grouped by source pipeline phase.",
            "Group annotations by phase.",
            # Co-occurrence analysis
            "What percentage of SYMBOL nodes have at least one quality annotation?",
            "Which annotation types co-occur most on the same node?",
            "Show annotation overlap.",
            # Equipment with quality issues
            "Which valves have flow problems?",
            "Show tanks with quality annotations.",
            "List equipment with issues.",
            # Generic multi-domain
            "Show cross-domain relationships.",
            "List multi-entity patterns.",
        ],
        "warnings": [
            "COVERS direction: (lps:LogicalPipeSegment)-[:COVERS]->(ps:PipeSegment). Never reverse.",
            "Valve/instrument on a LogicalPipeSegment: "
            "MATCH (n:Node)<-[:CONTAINS]-(ps:PipeSegment)<-[:COVERS]-(lps:LogicalPipeSegment).",
            "flow_state valid values: 'SEEDED', 'PROPAGATED', 'UNKNOWN'. No 'ANNOTATED'.",
            "Connected between two symbol types = PIPE*1..20 path, NOT a single hop.",
            "ANNOTATES direction is always (Annotation)-[:ANNOTATES]->(target). Never reverse.",
            "Summary annotations target PID nodes: (Annotation)-[:ANNOTATES]->(p:PID). "
            "Use this for esv_total, kav_total, esv_types, kav_types.",
            "flow_direction IS NULL when flow_state is UNKNOWN/BLOCKED/SEEDED_UNKNOWN — never test WHERE flow_direction = 'UNKNOWN'.",
        ],
        "traversal": (
            "Node ↔ PIPE ↔ Node (topology) | "
            "Node ← CONTAINS ← PipeSegment ← COVERS ← LogicalPipeSegment | "
            "Node → ENDPOINT_OF → LogicalPipeSegment | "
            "Annotation → ANNOTATES → Node | LPS | PipeSegment | PID | Annotation"
        ),
        "esv_kav_summary_cypher": (
            "-- PID-level summary annotation — use for esv_total, kav_total, esv_types, kav_types: "
            "MATCH (ann:Annotation)-[:ANNOTATES]->(p:PID {pid_id:$pid_id}) "
            "WHERE ann.esv_total IS NOT NULL "
            "RETURN ann.esv_total, ann.esv_types, ann.kav_total, ann.kav_types, ann.total_types"
        ),
        "esv_kav_breakdown_cypher": (
            "MATCH (ann:Annotation {pid_id:$pid_id}) "
            "WHERE ann.category IS NOT NULL "
            "RETURN ann.category, ann.type, count(*) AS n ORDER BY ann.category, n DESC"
        ),
        "hitl_severity_cypher": (
            "MATCH (ann:Annotation {pid_id:$pid_id, hitl_severity:'HIGH'}) "
            "RETURN ann.id, ann.type, ann.audience, ann.source ORDER BY ann.type LIMIT 50"
        ),
        "equipment_semantics_cypher": (
            "MATCH (ann:Annotation {pid_id:$pid_id, intent:'equipment_semantics'}) "
            "RETURN ann.id, ann.type, ann.equipment_id, ann.target_id LIMIT 50"
        ),
        "evidence_semantics_cypher": (
            "MATCH (e:Evidence {pid_id:$pid_id, source:'phase3_equipment_semantics'}) "
            "RETURN e.id, e.equipment_id, e.equipment_label, e.role, "
            "e.observed_direction, e.confidence LIMIT 50"
        ),
        "annotation_by_intent_cypher": (
            "MATCH (ann:Annotation {pid_id:$pid_id}) "
            "WHERE ann.intent IS NOT NULL "
            "RETURN ann.intent, count(*) AS n ORDER BY n DESC"
        ),
        "annotation_by_source_cypher": (
            "MATCH (ann:Annotation {pid_id:$pid_id}) "
            "WHERE ann.source IS NOT NULL "
            "RETURN ann.source, count(*) AS n ORDER BY n DESC"
        ),
        "phase4_hint_cypher": (
            "MATCH (ann:Annotation {pid_id:$pid_id}) "
            "WHERE ann.phase4_hint IS NOT NULL "
            "RETURN ann.phase4_hint, count(*) AS n ORDER BY n DESC"
        ),
        "propagation_blocked_cypher": (
            "MATCH (ann:Annotation {pid_id:$pid_id, propagation_blocked:true})"
            "-[:ANNOTATES]->(lps:LogicalPipeSegment) "
            "RETURN lps.id, ann.type, ann.phase4_hint LIMIT 50"
        ),
    },

    "custom_query": {
        "description": (
            "Catch-all for ad-hoc or multi-hop queries that do not map cleanly to "
            "a single capability above. Use the full schema to compose any valid "
            "read-only Cypher query. "
            "All node/relationship types, properties, and traversal directions are "
            "documented in this file."
        ),
        "example_questions": [
            "Any question combining multiple node types.",
            "Statistical aggregations across the whole graph.",
            "Multi-hop path queries.",
        ],
        "guidance": (
            "1. Identify the anchor node type(s) from NODE_PROPERTIES. "
            "2. Identify the traversal pattern from RELATIONSHIPS. "
            "3. Apply QUERY_RULES to avoid common mistakes. "
            "4. Always LIMIT results. Always alias aggregations."
        ),
    },
}


# ---------------------------------------------------------------------------
# Critical query rules — injected into every LLM system prompt
# ---------------------------------------------------------------------------

QUERY_RULES = """
CRITICAL RULES — violating any of these produces wrong or empty results:

1.  No tag names exist. Identity = Node.id (e.g. "valve94") or Node.label (symbol class).

2.  structural_type has 2 confirmed values in live DB: SYMBOL | CONNECTOR
    - SYMBOL    = equipment and process symbols (tank, valve, instrumentation, general,
                  arrow, crossing, inlet/outlet)
    - CONNECTOR = label='connector' — pipe path intermediates, always degree=2
    - background nodes are FILTERED at Phase 0 and never loaded into Neo4j.
                  Exclude defensively with: WHERE n.label <> 'background'

3.  NEVER use structural_type='BOUNDARY' to find external interfaces.
    External interfaces = Node.label = 'inlet/outlet'  (these are SYMBOL type)

4.  Node.label is the symbol CLASS, not OCR text:
    tank | valve | instrumentation | general | arrow | crossing | inlet/outlet |
    connector | background

    PUMP QUERY CRITICAL: there is NO label='pump' in the graph.
    Pump units are label='tank' with functional_label='pump' (set by Phase 1
    on tank nodes with bbox width < 100px — condensate pump units CND-PU-xxx).
    ALL pump queries must use:  n.label = 'tank' AND n.functional_label = 'pump'
    Omitting functional_label='pump' returns ALL tanks (both vessels and pumps).

5.  PIPE (not CONNECTED) is the Node-level pipe adjacency relationship.
    PIPE is stored as directed in the graphml but TRAVERSE BOTH DIRECTIONS
    for undirected topology: (a)-[:PIPE]-(b)
    For resolved flow direction use LogicalPipeSegment.flow_direction.

6.  flow_state must be checked before using flow_direction:
    flow_state = 'UNKNOWN'               →  flow_direction is NULL (property absent/removed)
    flow_state = 'BLOCKED'               →  flow_direction is NULL (property absent/removed)
    flow_state = 'SEEDED_UNKNOWN'        →  flow_direction is NULL (contradictory evidence)
    flow_state IN ['SEEDED','PROPAGATED'] →  flow_direction has a value (FORWARD | REVERSE)
    NEVER use flow_state = 'ANNOTATED' — that value does not exist in the graph.
    NEVER test flow_direction = 'UNKNOWN' — 'UNKNOWN' is NOT a valid flow_direction value;
    use flow_state = 'UNKNOWN' instead.

7.  Evidence.direction and Evidence.observed_direction are both present.
    Prefer observed_direction as the canonical resolved value.
    Use direction_hint as a secondary signal when observed_direction is absent.

8.  Quality issues are PRE-COMPUTED as Annotation nodes. Use Annotation.type.
    Do NOT recompute structural checks with WHERE NOT (...) unless Annotation
    provably misses your case.

9.  JOINS_AT.trace_nodes[1] = the junction symbol (valve/arrow/tank between
    two segments). Indices 0 and 2 are connector nodes.

10. inlet/outlet nodes ALWAYS connect via exactly one CONNECTOR intermediate.
    They are never directly connected to other SYMBOL nodes.

11. background nodes are always degree=0.
    Exclude with:  WHERE n.label <> 'background'
    or:            WHERE n.structural_type <> 'BOUNDARY'

12. Duplicate rows in undirected PIPE traversal queries are normal.
    Use DISTINCT to deduplicate.

13. All queries must be READ-ONLY.
    No CREATE, MERGE, SET, DELETE, REMOVE, DETACH.

14. Always LIMIT list queries. Default LIMIT 50.

15. Always alias aggregations:
    count(n) AS total   ✓
    bare count(n)        ✗

16. HAS_ANNOTATION links PID → AnnotationRequest (not PID → Annotation).
    Annotation nodes are linked via ANNOTATES from the Annotation side.

17. AnnotationRequest.CONCERNS → Node is the path to the flagged node.
    Do not confuse AnnotationRequest with Annotation — they are different node types.

18. ADJACENT_VIA_NODES exists on both LogicalPipeSegment and PipeSegment.
    via_nodes (LIST) and via_count (INTEGER) are its properties.

19. PID→CONTAINS→Node IS a valid relationship (confirmed in live DB).
    Two equivalent ways to scope a query to one drawing:
    Option A — traverse from PID (use when you need PID properties):
        MATCH (p:PID {pid_id:$pid_id})-[:CONTAINS]->(n:Node)
    Option B — WHERE filter (simpler, preferred for pure Node queries):
        MATCH (n:Node) WHERE n.pid_id = $pid_id
    Both are correct. Do NOT use BOTH in the same query — that would be redundant.
    pid_id property exists on Node, PipeSegment, LogicalPipeSegment, Annotation, Arrow, Evidence.

20. "Connected" between two symbol types means reachable via PIPE path of any length,
    NOT just a single direct PIPE hop. Use variable-length traversal:
        MATCH (a:Node {label:'valve', pid_id:$pid_id})
        MATCH (b:Node {label:'tank',  pid_id:$pid_id})
        WHERE EXISTS { MATCH (a)-[:PIPE*1..20]-(b) }
    A single-hop check (a)-[:PIPE]-(b) will almost always return zero for
    symbol-to-symbol connectivity in a real P&ID.
""".strip()


# ---------------------------------------------------------------------------
# Schema string builder — for LLM system prompts
# ---------------------------------------------------------------------------

def build_schema_prompt() -> str:
    """
    Returns the complete grounded schema as a formatted string for injection
    into LLM system prompts.  Covers nodes, relationships, enums, rules,
    capability map, and example Cypher patterns.
    """
    lines = ["=== GROUNDED PID GRAPH SCHEMA ===\n"]

    # ── Node labels ──────────────────────────────────────────────────────
    lines.append("NODE LABELS AND PROPERTY KEYS:")
    for label, props in NODE_PROPERTIES.items():
        lines.append(f"  ({label})")
        lines.append(f"    props: {', '.join(props)}")
    lines.append("")

    # ── structural_type ───────────────────────────────────────────────────
    lines.append("Node.structural_type VALUES:")
    for st, desc in STRUCTURAL_TYPES.items():
        lines.append(f"  '{st}': {desc}")
    lines.append("")

    # ── Node.label ────────────────────────────────────────────────────────
    lines.append("Node.label VALUES (symbol classes):")
    lines.append(f"  {', '.join(NODE_LABEL_VALUES)}")
    lines.append("")

    # ── Relationships ─────────────────────────────────────────────────────
    lines.append("VALID TRAVERSAL PATTERNS:")
    for frm, rel, to, props in RELATIONSHIPS:
        prop_str = f"  props: [{', '.join(props)}]" if props else ""
        lines.append(f"  ({frm})-[:{rel}]->({to}){prop_str}")
    lines.append("")

    # ── Query rules ───────────────────────────────────────────────────────
    lines.append(QUERY_RULES)
    lines.append("")

    # ── Annotation types ──────────────────────────────────────────────────
    lines.append("Annotation.type VALUES AND THEIR TARGET NODE TYPES:")
    for t, target in ANNOTATION_TYPE_TARGET.items():
        lines.append(f"  '{t}' → annotates {target}")
    lines.append("")

    # ── Capability map summary ────────────────────────────────────────────
    lines.append("CAPABILITY BUCKETS (intent routing):")
    for cap, meta in CAPABILITY_MAP.items():
        lines.append(f"  [{cap}]")
        lines.append(f"    {meta['description']}")
        if "example_questions" in meta:
            for q in meta["example_questions"]:
                lines.append(f"    • {q}")
        if "example_cypher" in meta:
            lines.append(f"    EXAMPLE:\n      {meta['example_cypher']}")
        lines.append("")

    return "\n".join(lines)


# Cached string — built once at import time
SCHEMA_PROMPT: str = build_schema_prompt()


# ---------------------------------------------------------------------------
# Compact schema prompt — used by GroundedGenerator (LLM Cypher generation)
#
# The full SCHEMA_PROMPT is ~7800 tokens — too large for free-tier LLM APIs
# (Groq llama-3.1-8b-instant limit: 6000 TPM).  This compact version keeps
# only what the LLM needs to generate correct Cypher:
#   • Node labels + minimal key properties
#   • All relationships (essential traversal)
#   • 12 critical QUERY_RULES (no examples)
#   • Annotation types + targets
#   • Capability descriptions + warnings + example_cypher
#   OMITS: example_questions (intent routing only), verbose property lists,
#          secondary Cypher examples, corpus/global stats nodes
# Target: ~2500 tokens so total LLM request stays under 5000 tokens
# ---------------------------------------------------------------------------

_COMPACT_QUERY_RULES = """
CRITICAL RULES:
1. No tag names. Identity = Node.id (e.g. "valve94") or Node.label.
2. structural_type: SYMBOL | CONNECTOR only. 'BOUNDARY' does NOT exist in DB.
   background nodes are never loaded — exclude with: n.label <> 'background'
3. External interfaces = Node.label = 'inlet/outlet' (SYMBOL type, NOT BOUNDARY).
4. PUMP: NO label='pump'. Pumps = label='tank' AND functional_label='pump'.
5. PIPE (not CONNECTED) is undirected node adjacency. Traverse both directions: (a)-[:PIPE]-(b).
6. flow_state before flow_direction:
   UNKNOWN/BLOCKED/SEEDED_UNKNOWN -> flow_direction IS NULL
   SEEDED/PROPAGATED -> flow_direction = 'FORWARD' | 'REVERSE'
   NEVER test flow_direction = 'UNKNOWN' — use flow_state = 'UNKNOWN'.
7. Evidence.observed_direction is the canonical value (not direction).
8. Quality issues = pre-computed Annotation nodes. Use Annotation.type; do NOT recompute.
9. Equipment connects via CONNECTOR intermediates — never directly.
   Symbol-to-symbol connectivity requires PIPE*1..20, NOT a single hop.
10. Degree formula: size([(n)-[:PIPE]-(m:Node)|m]) AS degree.
11. COVERS direction: (lps:LogicalPipeSegment)-[:COVERS]->(ps:PipeSegment). Never reverse.
12. Always LIMIT list queries (default 50). Always alias aggregations: count(n) AS total.
13. PID scoping: WHERE n.pid_id = $pid_id OR MATCH (p:PID {pid_id:$pid_id})-[:CONTAINS]->(n).
    Do NOT use both in the same query.
14. ANNOTATES direction: (Annotation)-[:ANNOTATES]->(target). Never reverse.
15. HAS_ANNOTATION: (PID)-[:HAS_ANNOTATION]->(AnnotationRequest). AnnotationRequest != Annotation.
""".strip()

# Essential node properties (only what Cypher generation needs)
_COMPACT_NODE_PROPS = {
    "Node":                  ["id", "pid_id", "label", "structural_type", "functional_label",
                              "flow_direction", "flow_state", "flow_confidence", "xmin", "ymin", "xmax", "ymax"],
    "PID":                   ["pid_id", "status"],
    "PipeSegment":           ["id", "pid_id", "node_count", "component_id", "geometry_hash"],
    "LogicalPipeSegment":    ["id", "pid_id", "flow_state", "flow_direction", "flow_confidence",
                              "seed_confidence", "phase4_hint"],
    "Annotation":            ["id", "pid_id", "type", "pattern_type", "source", "target_id",
                              "node_id", "lps_id", "degree", "rarity_score", "rarity_label",
                              "hitl_severity", "category", "phase4_hint", "explanation",
                              "esv_total", "kav_total", "propagation_blocked"],
    "AnnotationRequest":     ["request_id", "pid_id", "node_id", "label", "anomaly_type",
                              "detail", "status"],
    "Evidence":              ["id", "pid_id", "observed_direction", "confidence", "role",
                              "source", "equipment_id", "equipment_label"],
    "Arrow":                 ["id", "pid_id"],
}


def build_schema_prompt_compact() -> str:
    """
    Compact schema for LLM Cypher generation — ~1000 tokens vs ~7800 for full.
    Contains only core schema facts: node labels+props, relationships, critical
    rules, and annotation types.  The per-intent capability context (warnings,
    examples) is injected separately by _build_system_prompt() in grounded_generator.py.
    Omits: example_questions (intent routing only), capability map (per-intent),
            verbose secondary property lists, corpus/global stats nodes.
    """
    lines = ["=== PID GRAPH SCHEMA (COMPACT) ===\n"]

    # Node labels + minimal props
    lines.append("NODE LABELS AND KEY PROPERTIES:")
    for label, props in _COMPACT_NODE_PROPS.items():
        lines.append(f"  ({label}): {', '.join(props)}")
    lines.append(f"\nNode.label values: {', '.join(NODE_LABEL_VALUES)}")
    lines.append("Node.structural_type: SYMBOL | CONNECTOR  (no BOUNDARY in DB)\n")

    # Relationships
    lines.append("TRAVERSAL PATTERNS:")
    for frm, rel, to, props in RELATIONSHIPS:
        prop_str = f" [{', '.join(props[:3])}{'...' if len(props)>3 else ''}]" if props else ""
        lines.append(f"  ({frm})-[:{rel}]->({to}){prop_str}")
    lines.append("")

    # Compact rules
    lines.append(_COMPACT_QUERY_RULES)
    lines.append("")

    # Annotation type → target (essential for Annotation queries)
    lines.append("Annotation.type -> target:")
    for t, target in ANNOTATION_TYPE_TARGET.items():
        lines.append(f"  '{t}' -> {target}")

    return "\n".join(lines)


# Cached compact string — built once at import time
SCHEMA_PROMPT_COMPACT: str = build_schema_prompt_compact()


# ---------------------------------------------------------------------------
# Minimal schema prompt — used by GroundedGenerator when the active model
# has a very small context budget (e.g. llama-3.1-8b-instant at 6k TPM).
#
# Contains ONLY: key traversal patterns + 15 critical rules.
# The per-intent capability context is still injected by _build_system_prompt().
# Target: ~400 tokens so total LLM request stays ~1200-1500 tokens.
# ---------------------------------------------------------------------------

def build_schema_prompt_minimal() -> str:
    """
    Ultra-compact schema — traversal patterns + critical rules only (~400 tokens).
    For small/rate-limited LLM models.
    """
    lines = ["=== PID GRAPH SCHEMA (MINIMAL) ==="]
    lines.append(f"Node labels: {', '.join(NODE_LABEL_VALUES)}")
    lines.append("structural_type: SYMBOL | CONNECTOR  (BOUNDARY never in DB)")
    lines.append("PUMP = label='tank' AND functional_label='pump'  (NO label='pump')\n")

    lines.append("KEY TRAVERSAL PATTERNS:")
    # Only the most commonly needed relationships
    _key_rels = {
        "PIPE", "ENDPOINT_OF", "COVERS", "ADJACENT_VIA_NODES",
        "ANNOTATES", "CONTAINS", "FLOW_EVIDENCE", "ABOUT",
        "HAS_ANNOTATION", "CONCERNS", "JOINS_AT",
    }
    for frm, rel, to, _ in RELATIONSHIPS:
        if rel in _key_rels:
            lines.append(f"  ({frm})-[:{rel}]->({to})")
    lines.append("")

    lines.append(_COMPACT_QUERY_RULES)
    return "\n".join(lines)


SCHEMA_PROMPT_MINIMAL: str = build_schema_prompt_minimal()
