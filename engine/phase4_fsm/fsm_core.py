# engine/phase4_fsm/fsm_core.py
#
# Phase 4 FSM — Evidence seeding + BFS propagation (pid-scoped, idempotent)
#
# REPLACES: engine/phase4_fsm/ingest_phase4_fsm.py
#
# 28 issues fixed across the old Phase 4 codebase.  Changes in this file:
#
# [IMPORT]    engine.phase0_ingestion.load_to_neo4j (was ingestion.load_to_neo4j)
# [NO_PID]    all queries scoped to pid_id
# [SEED]      seeds from Evidence -[:ABOUT]-> LPS (all sources)
#             OLD: Arrow -[:FLOW_EVIDENCE]-> LPS (arrow-only)
#             NEW: phase2_flow_evidence + phase3_boundary_semantics
#                  + phase3_equipment_semantics + phase3_check_valve
#                  + phase3_topology_inference
# [SEED]      uses lps.seed_confidence (Phase 3 R3) as initial flow_confidence
# [PROP_REL]  ADJACENT_VIA_NODES (confirmed LPS↔LPS in Phase 3)
#             OLD: JOINS_AT (not confirmed LPS↔LPS)
# [P3_SKIP]   pre-flight stamps phase4_blocked on LPS from rarity propagation_blocked
# [P3_SKIP]   pre-flight stamps phase4_hint / phase4_resolution_rule on LPS
#             from per-LPS structural annotations
# [P3_SKIP]   propagation skips source and target LPS with phase4_blocked=true
# [P3_SKIP]   conflict LPS with resolution_rule='hitl_required' → HITL_PENDING state
# [P3_SKIP]   warns when ESV corpus_normalized=False (provisional single-PID rarity)
# [TRACE]     trace path moved to logs/phase4_trace_{pid_id}.json (caller handles)
# [ENG_RULES] pre-flight now also stamps phase4_blocked on LPS connected (via
#             ENDPOINT_OF) to equipment nodes bearing Phase 3.5 safety-critical
#             engineering rule violations. These annotations target Node instances,
#             not LPS directly, so a dedicated sub-step is required.
#
# FSM STATES:
#   SEEDED         — directional vote from Evidence ≥ threshold
#   SEEDED_UNKNOWN — Evidence present but vote too weak to resolve direction
#   HITL_PENDING   — conflict annotation with resolution_rule='hitl_required'
#   PROPAGATED     — reached by BFS from a SEEDED neighbour
#   BLOCKED        — phase4_blocked=true (structural flaw, skipped entirely)
#   UNKNOWN        — no Evidence and not reachable from any seed

from __future__ import annotations

import logging
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────────

DECAY: float = 0.8           # confidence multiplier per BFS hop
BRANCH_DECAY: float = 0.85   # extra multiplier at conflict/branch LPS
MIN_CONFIDENCE: float = 0.05  # BFS stops propagating when confidence drops below
MAX_ITERATIONS: int = 100    # hard cap on BFS rounds

# Weighted vote: if |net_score| < UNCERTAIN_THR * total_confidence → UNKNOWN
UNCERTAIN_THR: float = 0.40


# ── Phase 3.5 safety-critical engineering rule violations ────────────────────────
#
# LPS connected (via Node-[:ENDPOINT_OF]->) to equipment nodes bearing any of
# these Phase 3.5 violations are unconditionally blocked from FSM propagation.
#
# Engineering rationale:
#   A pump with no check valve (missing_check_valve) means backflow could corrupt
#   any direction the FSM propagates from that LPS.  Stamping propagation_blocked
#   prevents the FSM from seeding faulty direction vectors into the network.
#
# These annotations target Node instances (not LPS directly), so the existing
# rarity-based blocked_count query in _preflight cannot catch them.  A separate
# sub-step (_preflight_eng_rule_blocks) handles the Node→LPS path.
#
# MUST stay in sync with:
#   engine.phase3_annotation.rarity_scoring._UNCONDITIONALLY_BLOCKED
#   (the engineering-rule subset — structural KOS patterns are handled separately)

_SAFETY_CRITICAL_RULE_VIOLATIONS: frozenset[str] = frozenset({
    "missing_check_valve",              # Backflow prevention — CRITICAL
    "missing_pressure_relief_valve",    # Overpressure protection — CRITICAL
    "missing_warming_coil",             # Cryogenic safety — CRITICAL
    "missing_cooling_jacket",           # High-temperature safety — CRITICAL
})


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _scalar(session, q: str, params: dict | None = None, key: str = "c") -> int:
    r = session.run(q, **(params or {})).single()
    return int(r[key]) if r and r.get(key) is not None else 0


def _P(pid_id: str) -> dict:
    return {"pid_id": pid_id}


# ── Step 0a: Pre-flight — structural rarity blocks ────────────────────────────

def _preflight_structural_blocks(session, pid_id: str) -> int:
    """
    Stamp phase4_blocked=true on LPS annotated with propagation_blocked rarity
    patterns (e.g. logical_not_covered, logical_missing_endpoints).

    These annotations have (Annotation)-[:ANNOTATES]->(LPS) directly.
    Returns count of LPS newly blocked.
    """
    blocked_count = _scalar(session, """
        MATCH (r:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity',
                             propagation_blocked:true})
        WITH collect(DISTINCT r.pattern_type) AS blocked_patterns
        MATCH (a:Annotation {pid_id:$pid_id})-[:ANNOTATES]->(lps:LogicalPipeSegment)
        WHERE a.pattern_type IN blocked_patterns
        SET lps.phase4_blocked = true,
            a.propagation_blocked = true
        RETURN count(DISTINCT lps) AS c
    """, _P(pid_id))

    if blocked_count > 0:
        logger.info(
            "[PHASE4][PREFLIGHT] phase4_blocked=true stamped on %d LPS "
            "(structural rarity — propagation_blocked patterns)",
            blocked_count,
        )
    return blocked_count


# ── Step 0b: Pre-flight — Phase 3.5 engineering rule violation blocks ─────────

def _preflight_eng_rule_blocks(session, pid_id: str) -> int:
    """
    Stamp phase4_blocked=true on LPS connected (via ENDPOINT_OF) to equipment
    nodes that carry safety-critical Phase 3.5 engineering rule violations.

    WHY A SEPARATE STEP:
      Engineering rule violation Annotations target Node instances (equipment),
      not LogicalPipeSegment nodes.  The existing structural-rarity block step
      queries (Annotation)-[:ANNOTATES]->(LPS) and will never see these.
      We propagate the block through the Node-[:ENDPOINT_OF]->(LPS) edge.

    WHICH VIOLATIONS TRIGGER BLOCKING:
      Only _SAFETY_CRITICAL_RULE_VIOLATIONS — the four patterns that are also
      in rarity_scoring._UNCONDITIONALLY_BLOCKED.  Non-critical violations
      (missing_isolation_valve, tank_vent_position_violation, etc.) are resolved
      in Phase 7 HITL and must NOT block propagation here.

    Returns count of LPS newly blocked by engineering violations.
    """
    if not _SAFETY_CRITICAL_RULE_VIOLATIONS:
        return 0

    eng_blocked = _scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'})
        WHERE a.pattern_type IN $safety_violations
        MATCH (a)-[:ANNOTATES]->(n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$pid_id})
        SET lps.phase4_blocked = true,
            lps.phase4_hint    = 'block_propagation_safety_violation'
        RETURN count(DISTINCT lps) AS c
    """, {**_P(pid_id), "safety_violations": list(_SAFETY_CRITICAL_RULE_VIOLATIONS)})

    if eng_blocked > 0:
        logger.info(
            "[PHASE4][PREFLIGHT] phase4_blocked=true stamped on %d LPS "
            "(Phase 3.5 safety-critical engineering rule violations: %s)",
            eng_blocked,
            ", ".join(sorted(_SAFETY_CRITICAL_RULE_VIOLATIONS)),
        )
    return eng_blocked


# ── Step 0c: Pre-flight — Global Statistical Knowledge Layer (C19) ────────────

def _apply_global_statistics(session, pid_id: str) -> int:
    """
    Consult GlobalStatistic nodes (built by global_statistics.py) to adjust
    seed_confidence on LPS whose structural patterns are globally rare.

    ARCHITECTURE FLOW: Global Statistical Knowledge Layer → Phase 4 (C19)

    Adjustment logic:
      - globally_absent / globally_rare → multiply seed_confidence by 1.25
        (rare patterns are stronger directional signals)
      - globally_dominant → multiply seed_confidence by 0.85
        (common patterns carry less directional weight)
      - all others → no adjustment

    Only applies when GlobalStatistic nodes exist (i.e., after run_phase7.py
    has built the global layer).  If no nodes exist, returns 0 (no-op).

    Returns count of LPS whose seed_confidence was adjusted.
    """
    # Check if global statistics exist at all.
    # Query db.labels() first so we never reference an absent label and avoid
    # the Neo.ClientNotification.Statement.UnknownLabelWarning.
    label_exists = _scalar(session,
        "CALL db.labels() YIELD label WHERE label = 'GlobalStatistic' RETURN count(*) AS c")
    has_global = 0 if label_exists == 0 else _scalar(session,
        "MATCH (gs:GlobalStatistic) RETURN count(gs) AS c")
    if has_global == 0:
        logger.info(
            "[PHASE4][PREFLIGHT] No GlobalStatistic nodes found — "
            "skipping global rarity adjustment (run Phase 7 to build them)."
        )
        return 0

    # Boost seed_confidence for LPS annotated with globally rare patterns
    boosted = _scalar(session, """
        MATCH (gs:GlobalStatistic)
        WHERE gs.global_rarity IN ['globally_absent', 'globally_rare']
        WITH collect(gs.pattern_type) AS rare_patterns
        MATCH (a:Annotation {pid_id: $pid_id})-[:ANNOTATES]->(lps:LogicalPipeSegment)
        WHERE a.pattern_type IN rare_patterns
          AND lps.seed_confidence IS NOT NULL
          AND lps.seed_confidence > 0
        SET lps.seed_confidence = round(lps.seed_confidence * 1.25 * 1000) / 1000.0,
            lps.global_rarity_boost = true
        RETURN count(DISTINCT lps) AS c
    """, _P(pid_id))

    # Reduce seed_confidence for LPS annotated with globally dominant patterns
    reduced = _scalar(session, """
        MATCH (gs:GlobalStatistic)
        WHERE gs.global_rarity = 'globally_dominant'
        WITH collect(gs.pattern_type) AS dominant_patterns
        MATCH (a:Annotation {pid_id: $pid_id})-[:ANNOTATES]->(lps:LogicalPipeSegment)
        WHERE a.pattern_type IN dominant_patterns
          AND lps.seed_confidence IS NOT NULL
          AND lps.seed_confidence > 0
          AND NOT coalesce(lps.global_rarity_boost, false)
        SET lps.seed_confidence = round(lps.seed_confidence * 0.85 * 1000) / 1000.0,
            lps.global_rarity_reduced = true
        RETURN count(DISTINCT lps) AS c
    """, _P(pid_id))

    total = boosted + reduced
    if total > 0:
        logger.info(
            "[PHASE4][PREFLIGHT] Global statistics applied: "
            "%d LPS boosted (globally rare), %d LPS reduced (globally dominant)",
            boosted, reduced,
        )
    else:
        logger.info(
            "[PHASE4][PREFLIGHT] Global statistics checked — "
            "no seed_confidence adjustments needed."
        )

    return total


# ── Step 0: Pre-flight (orchestrates 0a + 0b) ───────────────────────────────────

def _preflight(session, pid_id: str) -> Dict[str, Any]:
    """
    Validate Phase 3 contracts and stamp actionable flags onto LPS nodes.

    Stamps written to LPS (transient, cleared by clear_phase4_data):
      lps.phase4_blocked          = true     (structural rarity OR safety rule violation)
      lps.phase4_hint             = str      (highest-priority pattern or 'block_propagation_safety_violation')
      lps.phase4_resolution_rule  = str|null (from direction_conflict_observed)

    Sub-steps:
      0a: structural rarity blocks (propagation_blocked=true on rarity annotations)
      0b: Phase 3.5 engineering rule violation blocks (safety-critical, via Node→LPS)
      0c: Global Statistical Knowledge Layer consultation (C19 — adjusts seed_confidence)

    Raises RuntimeError if no LPS or no directional Evidence found.
    Logs warnings for provisional ESV rarity (corpus_normalized=False).
    """
    lps_count = _scalar(session,
        "MATCH (lps:LogicalPipeSegment {pid_id:$pid_id}) RETURN count(lps) AS c",
        _P(pid_id))

    if lps_count == 0:
        raise RuntimeError(
            f"Phase 4 aborted — no LogicalPipeSegment for pid_id={pid_id}. "
            "Run Phases 0→3 first."
        )

    evidence_count = _scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
              <-[:ABOUT]-(e:Evidence {pid_id:$pid_id})
        WHERE e.observed_direction IN ['FORWARD','REVERSE']
        RETURN count(DISTINCT lps) AS c
    """, _P(pid_id))

    if evidence_count == 0:
        raise RuntimeError(
            f"Phase 4 aborted — no directional Evidence for pid_id={pid_id}. "
            "Run run_phase3.py --pid first."
        )

    # Warn: provisional ESV rarity scores
    provisional_esv = _scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity',
                             category:'ESV', corpus_normalized:false})
        RETURN count(a) AS c
    """, _P(pid_id))
    if provisional_esv > 0:
        logger.warning(
            "[PHASE4][PREFLIGHT] %d ESV rarity annotations have corpus_normalized=False "
            "(provisional, single-PID). Phase 9 skid corpus run will normalise them.",
            provisional_esv
        )

    # Sub-step 0a: structural rarity blocks (LPS-annotated patterns)
    blocked_count = _preflight_structural_blocks(session, pid_id)

    # Sub-step 0b: Phase 3.5 engineering rule violation blocks (Node-annotated, via ENDPOINT_OF)
    eng_rule_blocked = _preflight_eng_rule_blocks(session, pid_id)

    # Sub-step 0c: Global Statistical Knowledge Layer consultation (C19)
    # If GlobalStatistic nodes exist (built by global_statistics.py / run_phase7.py),
    # adjust seed_confidence on LPS whose dominant structural pattern is globally
    # rare — these are stronger signals and deserve boosted confidence.
    global_stats_applied = _apply_global_statistics(session, pid_id)

    # Stamp phase4_hint on LPS from per-LPS structural annotations.
    # Priority order: conflict > unresolved > low_confidence > weak_consensus > gap
    # Also capture resolution_rule for conflict LPS (needed in seeding step).
    # NOTE: phase4_hint may already be set to 'block_propagation_safety_violation'
    # by sub-step 0b for safety-critical violations — this query only overwrites
    # LPS that do NOT yet have phase4_hint stamped (or where a higher-priority
    # direction annotation exists).
    # Step A: stamp annotation-based hints (conflict, unresolved, low-confidence).
    # direction_evidence_missing is no longer an Annotation — detected in Step B.
    session.run("""
        MATCH (a:Annotation {pid_id:$pid_id})-[:ANNOTATES]->(lps:LogicalPipeSegment)
        WHERE a.pattern_type IN [
            'direction_conflict_observed',
            'lps_direction_unresolved',
            'lps_low_confidence_evidence',
            'lps_weak_evidence_consensus'
        ]
        WITH lps, a
        ORDER BY
          CASE a.pattern_type
            WHEN 'direction_conflict_observed'  THEN 0
            WHEN 'lps_direction_unresolved'     THEN 1
            WHEN 'lps_low_confidence_evidence'  THEN 2
            WHEN 'lps_weak_evidence_consensus'  THEN 3
            ELSE 4 END
        WITH lps, collect(a)[0] AS top
        SET lps.phase4_hint            = top.pattern_type,
            lps.phase4_resolution_rule = top.resolution_rule
    """, pid_id=pid_id)

    # Step B: stamp gap hint directly — LPS with no Evidence and no higher-priority
    # hint already set. Avoids heavyweight Annotation nodes for a structural absence.
    session.run("""
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE NOT EXISTS { MATCH (lps)<-[:ABOUT]-(:Evidence {pid_id:$pid_id}) }
          AND lps.phase4_hint IS NULL
        SET lps.phase4_hint = 'direction_evidence_missing'
    """, pid_id=pid_id)

    total_blocked = blocked_count + eng_rule_blocked

    logger.info(
        "[PHASE4][PREFLIGHT] LPS=%d  directional_seeds=%d  "
        "structural_blocked=%d  eng_rule_blocked=%d  total_blocked=%d",
        lps_count, evidence_count,
        blocked_count, eng_rule_blocked, total_blocked,
    )

    return {
        "lps_count":         lps_count,
        "evidence_count":    evidence_count,
        "blocked_count":     blocked_count,       # structural rarity blocks
        "eng_rule_blocked":  eng_rule_blocked,    # Phase 3.5 safety violation blocks
        "total_blocked":     total_blocked,
        "provisional_esv":   provisional_esv,
        "global_stats_applied": global_stats_applied,  # C19: global rarity adjustments
    }


# ── Step 1: Reset ────────────────────────────────────────────────────────────────

def _reset(session, pid_id: str) -> None:
    """Remove all flow_state properties from LPS for this PID."""
    session.run("""
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        REMOVE lps.flow_state, lps.flow_direction,
               lps.flow_confidence, lps.flow_source,
               lps.flow_exit_node_id
    """, pid_id=pid_id)
    logger.info("[PHASE4][RESET] Flow state cleared for PID=%s", pid_id)


# ── Step 2: Seed from Evidence ────────────────────────────────────────────────────

def _seed(session, pid_id: str) -> Tuple[int, int]:
    """
    Assign initial flow_direction to LPS that have Evidence.

    Two-pass seeding:
      Pass A — HITL_PENDING: LPS with resolution_rule='hitl_required' on their
               conflict annotation. Phase 7 HITL will resolve these manually.
               Not seeded — left for BFS if reachable, or HITL review otherwise.

      Pass B — Weighted vote over all Evidence for this LPS:
               score = Σ(e.confidence * direction_sign)
               FORWARD → +1, REVERSE → -1, UNKNOWN → 0
               If |score| < UNCERTAIN_THR * total → direction = 'UNKNOWN'
               flow_confidence = lps.seed_confidence if > 0, else total_conf

    Blocked LPS (phase4_blocked=true) are skipped in both passes.

    Returns (seeded_count, hitl_pending_count).
    """
    # Pass A: HITL-required conflict LPS
    hitl_count = _scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id,
                                       phase4_resolution_rule:'hitl_required'})
        WHERE NOT coalesce(lps.phase4_blocked, false)
        SET lps.flow_state      = 'HITL_PENDING',
            lps.flow_direction  = 'UNKNOWN',
            lps.flow_confidence = 0.0,
            lps.flow_source     = 'hitl_required'
        RETURN count(lps) AS c
    """, _P(pid_id))

    # Pass B: Weighted vote from Evidence (all sources).
    # FIX-9: phase4_blocked filter removed. Blocked LPS with directional evidence
    # must still be seeded so their direction is recorded. Propagation already
    # excludes blocked LPS as sources/targets via the nbr filter in _propagate().
    #
    # FIX-10: Only FORWARD/REVERSE Evidence participates in seeding.
    # UNKNOWN-direction Evidence (e.g. from phase3_topology_inference that could
    # not resolve direction) adds no net_score but inflates total_conf, causing
    # LPS with zero directional signal to be falsely marked SEEDED_UNKNOWN and
    # blocking BFS propagation.  Excluding UNKNOWN evidence lets those LPS remain
    # unresolved so BFS can propagate a direction from adjacent resolved LPS.
    seeded = _scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.flow_state IS NULL
        MATCH (lps)<-[:ABOUT]-(e:Evidence {pid_id:$pid_id})
        WHERE e.observed_direction IN ['FORWARD','REVERSE']
        WITH lps,
             collect({d: e.observed_direction,
                      c: coalesce(toFloat(e.confidence), 0.0)}) AS votes,
             coalesce(toFloat(lps.seed_confidence), 0.0) AS sc
        WITH lps, votes, sc,
             reduce(s = 0.0, v IN votes |
                    s + v.c * CASE v.d
                                WHEN 'FORWARD' THEN 1.0
                                WHEN 'REVERSE' THEN -1.0
                                ELSE 0.0 END
             ) AS net_score,
             reduce(t = 0.0, v IN votes | t + v.c) AS total_conf
        WITH lps, sc, net_score, total_conf,
             CASE
               WHEN total_conf = 0 OR abs(net_score) < $thr * total_conf
                    THEN 'UNKNOWN'
               WHEN net_score > 0
                    THEN 'FORWARD'
               ELSE      'REVERSE'
             END AS chosen
        SET lps.flow_direction  = CASE WHEN chosen = 'UNKNOWN' THEN null ELSE chosen END,
            lps.flow_confidence = CASE WHEN sc > 0.0
                                       THEN CASE WHEN sc > 1.0 THEN 1.0 ELSE sc END
                                       ELSE CASE WHEN round(total_conf * 1000) / 1000.0 > 1.0
                                                 THEN 1.0
                                                 ELSE round(total_conf * 1000) / 1000.0 END
                                  END,
            lps.flow_state      = CASE WHEN chosen = 'UNKNOWN'
                                       THEN 'SEEDED_UNKNOWN'
                                       ELSE 'SEEDED'
                                  END,
            lps.flow_source     = 'evidence'
        RETURN count(lps) AS c
    """, {**_P(pid_id), "thr": UNCERTAIN_THR})

    if hitl_count > 0:
        logger.info(
            "[PHASE4][SEED] HITL_PENDING=%d (resolution_rule=hitl_required)", hitl_count
        )
    logger.info("[PHASE4][SEED] Seeded=%d (SEEDED + SEEDED_UNKNOWN)", seeded)

    return seeded, hitl_count


# ── Step 2b: Stamp exit-node IDs on seeded LPS ──────────────────────────────────

def _stamp_exit_nodes(session, pid_id: str) -> int:
    """
    For every SEEDED LPS with a FORWARD/REVERSE direction, record which of its
    two endpoint nodes flow EXITS from.

    Convention (mirrors Phase 2 spatial_sort):
      Dominant axis = x when |cx2-cx1| >= |cy2-cy1|, else y.
      The spatially-first endpoint (lower coordinate on dominant axis) is the
      'start'; the spatially-last is the 'end'.
        FORWARD  →  flow exits from the END endpoint (higher coord)
        REVERSE  →  flow exits from the START endpoint (lower coord)

    This enables propagation to advance only through the correct (downstream)
    end of each source LPS and to compute the geometrically-correct direction
    for each target LPS, avoiding the U-turn and bidirectional-propagation bugs.
    """
    stamped = _scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.flow_state IN ['SEEDED']
          AND lps.flow_direction IN ['FORWARD', 'REVERSE']
          AND lps.flow_exit_node_id IS NULL
        MATCH (n1:Node)-[:ENDPOINT_OF]->(lps)
        MATCH (n2:Node)-[:ENDPOINT_OF]->(lps) WHERE n2.id > n1.id
        WITH lps, n1, n2,
             toFloat(coalesce(n1.xmin, 0) + coalesce(n1.xmax, 0)) / 2.0 AS cx1,
             toFloat(coalesce(n1.ymin, 0) + coalesce(n1.ymax, 0)) / 2.0 AS cy1,
             toFloat(coalesce(n2.xmin, 0) + coalesce(n2.xmax, 0)) / 2.0 AS cx2,
             toFloat(coalesce(n2.ymin, 0) + coalesce(n2.ymax, 0)) / 2.0 AS cy2
        WITH lps, n1, n2,
             // Forward exit = spatially-last (higher coord on dominant axis)
             CASE WHEN abs(cx2 - cx1) >= abs(cy2 - cy1)
                  THEN CASE WHEN cx1 <= cx2 THEN n2.id ELSE n1.id END
                  ELSE CASE WHEN cy1 <= cy2 THEN n2.id ELSE n1.id END
             END AS forward_exit_id,
             // Reverse exit = spatially-first (lower coord on dominant axis)
             CASE WHEN abs(cx2 - cx1) >= abs(cy2 - cy1)
                  THEN CASE WHEN cx1 <= cx2 THEN n1.id ELSE n2.id END
                  ELSE CASE WHEN cy1 <= cy2 THEN n1.id ELSE n2.id END
             END AS reverse_exit_id
        SET lps.flow_exit_node_id =
            CASE lps.flow_direction
              WHEN 'FORWARD' THEN forward_exit_id
              ELSE reverse_exit_id
            END
        RETURN count(lps) AS c
    """, _P(pid_id))
    logger.info("[PHASE4][STAMP] flow_exit_node_id stamped on %d SEEDED LPS", stamped)
    return stamped


# ── Step 3: BFS Propagation ───────────────────────────────────────────────────────

def _propagate(session, pid_id: str) -> int:
    """
    BFS propagation over ADJACENT_VIA_NODES (confirmed LPS↔LPS in Phase 3).

    Each iteration:
      Source: SEEDED or PROPAGATED LPS with flow_exit_node_id set.
              The exit node is the endpoint from which flow physically leaves
              the source LPS (FORWARD → spatially-last endpoint, REVERSE → first).
      Target: Any LPS adjacent to source that shares one of source's endpoints.
      Direction: computed geometrically from the shared node and the target's
                 other endpoint.  Two cases:
                 DOWNSTREAM (shared = source exit): flow enters target at shared,
                   exits target at the other endpoint.
                 UPSTREAM   (shared = source entry): flow exits target at shared
                   (so it can feed into source), enters target at other endpoint.
                 In both cases the formula is identical — the direction label is
                 determined by which of (target_entry, target_exit) has the
                 smaller coordinate on the dominant axis.
              This fixes two bugs in blind direction-copy:
                1. U-turn: adjacent LPS oriented the same way at the shared
                   node get FORWARD↔REVERSE flipped correctly.
                2. Bi-directional spread: every reachable LPS is visited but
                   each assignment is based on real physical geometry, not a
                   blind copy of the source's FORWARD/REVERSE label.
      Confidence: best.flow_confidence * DECAY
                  * BRANCH_DECAY if target has phase4_hint='direction_conflict_observed'

    Stops when no LPS can be newly reached (convergence) or MAX_ITERATIONS hit.
    Returns total propagated count.
    """
    total_propagated = 0

    for i in range(1, MAX_ITERATIONS + 1):
        propagated = _scalar(session, """
            MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
            WHERE lps.flow_state IS NULL
              AND NOT coalesce(lps.phase4_blocked, false)
            MATCH (lps)-[:ADJACENT_VIA_NODES]-(source:LogicalPipeSegment {pid_id:$pid_id})
            WHERE source.flow_state IN ['SEEDED','PROPAGATED']
              AND source.flow_direction IN ['FORWARD','REVERSE']
              AND source.flow_exit_node_id IS NOT NULL
              AND coalesce(toFloat(source.flow_confidence), 0.0) >= $min_conf
              AND NOT coalesce(source.phase4_blocked, false)
            // Find the shared endpoint (must be an endpoint of BOTH source and target).
            MATCH (shared:Node)-[:ENDPOINT_OF]->(source)
            MATCH (shared)-[:ENDPOINT_OF]->(lps)
            // Find the target's OTHER endpoint.
            MATCH (other:Node)-[:ENDPOINT_OF]->(lps)
            WHERE other.id <> shared.id
            // Determine target entry/exit based on propagation direction:
            //   DOWNSTREAM (shared = source exit) → flow enters target at shared,
            //                                        exits at other.
            //   UPSTREAM   (shared = source entry)→ flow exits target at shared,
            //                                        enters at other.
            WITH lps, source, shared, other,
                 CASE WHEN shared.id = source.flow_exit_node_id
                      THEN shared ELSE other  END AS target_entry_n,
                 CASE WHEN shared.id = source.flow_exit_node_id
                      THEN other  ELSE shared END AS target_exit_n
            ORDER BY source.flow_confidence DESC
            WITH lps,
                 collect(source)[0]        AS best,
                 collect(target_entry_n)[0] AS entry_n,
                 collect(target_exit_n)[0]  AS exit_n
            WITH lps, best, entry_n, exit_n,
                 toFloat(coalesce(entry_n.xmin, 0) + coalesce(entry_n.xmax, 0)) / 2.0 AS ecx,
                 toFloat(coalesce(entry_n.ymin, 0) + coalesce(entry_n.ymax, 0)) / 2.0 AS ecy,
                 toFloat(coalesce(exit_n.xmin,  0) + coalesce(exit_n.xmax,  0)) / 2.0 AS xcx,
                 toFloat(coalesce(exit_n.ymin,  0) + coalesce(exit_n.ymax,  0)) / 2.0 AS xcy
            // FORWARD = flow exits at the spatially-last endpoint (higher coord).
            // If entry_n has the LOWER coord on the dominant axis → spatial start →
            // flow goes start→end → FORWARD.  Higher coord → REVERSE.
            WITH lps, best, exit_n,
                 CASE WHEN abs(xcx - ecx) >= abs(xcy - ecy)
                      THEN CASE WHEN ecx <= xcx THEN 'FORWARD' ELSE 'REVERSE' END
                      ELSE CASE WHEN ecy <= xcy THEN 'FORWARD' ELSE 'REVERSE' END
                 END AS target_dir
            SET lps.flow_direction    = target_dir,
                lps.flow_exit_node_id = exit_n.id,
                lps.flow_confidence   = round(
                    toFloat(best.flow_confidence) * $decay *
                    CASE WHEN coalesce(lps.phase4_hint,'') = 'direction_conflict_observed'
                         THEN $branch_decay ELSE 1.0 END * 1000
                ) / 1000.0,
                lps.flow_state        = 'PROPAGATED',
                lps.flow_source       = 'propagated'
            RETURN count(lps) AS c
        """, {
            **_P(pid_id),
            "decay":        DECAY,
            "min_conf":     MIN_CONFIDENCE,
            "branch_decay": BRANCH_DECAY,
        })

        logger.info("[PHASE4][PROPAGATE] Iteration %d: propagated=%d", i, propagated)
        total_propagated += propagated

        if propagated == 0:
            break

    logger.info("[PHASE4][PROPAGATE] Total propagated=%d", total_propagated)
    return total_propagated


# ── Step 4: Mark BLOCKED / UNKNOWN ───────────────────────────────────────────────

def _mark_remaining(session, pid_id: str) -> Tuple[int, int]:
    """
    Assign terminal states to LPS that were not reached by seeding or BFS.

    BLOCKED  — phase4_blocked=true (structural flaw or safety rule violation)
    UNKNOWN  — no Evidence and not reachable from any seed
    """
    blocked = _scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.flow_state IS NULL
          AND coalesce(lps.phase4_blocked, false)
        SET lps.flow_state      = 'BLOCKED',
            lps.flow_confidence = 0.0,
            lps.flow_source     = 'propagation_blocked'
        RETURN count(lps) AS c
    """, _P(pid_id))

    unknown = _scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.flow_state IS NULL
        SET lps.flow_state      = 'UNKNOWN',
            lps.flow_confidence = 0.0,
            lps.flow_source     = 'none'
        RETURN count(lps) AS c
    """, _P(pid_id))

    if blocked > 0:
        logger.info("[PHASE4][MARK] BLOCKED=%d (structural flaw or safety violation)", blocked)
    logger.info("[PHASE4][MARK] UNKNOWN=%d (unreachable)", unknown)

    return unknown, blocked


# ── Step 5: State summary + trace ────────────────────────────────────────────────

def _collect_results(session, pid_id: str) -> Dict[str, Any]:
    state_dist = session.run("""
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        RETURN lps.flow_state AS state,
               count(lps)     AS n,
               avg(toFloat(coalesce(lps.flow_confidence, 0.0))) AS avg_conf
        ORDER BY n DESC
    """, pid_id=pid_id).data()

    trace_rows = session.run("""
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        RETURN lps.id              AS id,
               lps.flow_state      AS state,
               lps.flow_direction  AS direction,
               lps.flow_confidence AS confidence,
               lps.flow_source     AS source
    """, pid_id=pid_id).data()

    trace = {
        r["id"]: {
            "state":      r["state"],
            "direction":  r["direction"],
            "confidence": r["confidence"],
            "source":     r["source"],
        }
        for r in trace_rows
    }

    return {"state_dist": state_dist, "trace": trace}


# ── Main entry point ──────────────────────────────────────────────────────────────

def run_fsm(session, pid_id: str) -> Dict[str, Any]:
    """
    Run the Phase 4 FSM for a single PID.

    Caller must provide an open Neo4j session.
    Returns a result dict with keys:
      preflight, seeded, hitl_pending, total_propagated, unknown, blocked,
      state_dist, trace

    preflight dict includes:
      lps_count, evidence_count,
      blocked_count     (structural rarity propagation_blocked patterns),
      eng_rule_blocked  (Phase 3.5 safety-critical rule violation blocks),
      total_blocked     (blocked_count + eng_rule_blocked),
      provisional_esv

    The trace dict (lps_id → {state, direction, confidence, source}) is written
    to disk by the orchestrator (run_phase4.py).
    """
    logger.info("[PHASE4][FSM] ===== START | PID=%s =====", pid_id)

    preflight       = _preflight(session, pid_id)
    _reset(session, pid_id)
    seeded, hitl    = _seed(session, pid_id)
    _stamp_exit_nodes(session, pid_id)
    total_prop      = _propagate(session, pid_id)
    unknown, blocked = _mark_remaining(session, pid_id)
    result          = _collect_results(session, pid_id)

    logger.info("[PHASE4][FSM] State distribution for PID=%s:", pid_id)
    for r in result["state_dist"]:
        logger.info("  %-20s n=%-5d avg_conf=%.3f",
                    r["state"], int(r["n"]), float(r.get("avg_conf") or 0))

    result.update({
        "preflight":        preflight,
        "seeded":           seeded,
        "hitl_pending":     hitl,
        "total_propagated": total_prop,
        "unknown":          unknown,
        "blocked":          blocked,
    })

    logger.info("[PHASE4][FSM] ===== COMPLETE | PID=%s =====", pid_id)
    return result