# engine/phase3_annotation/rarity_scoring.py
#
# Phase 3 — Structural rarity scoring (pid-scoped)
#
# SCORING TRACKS:
#
# ESV track — absolute count tiers (PROVISIONAL, corpus_normalized=False).
#   corpus_normalized=False until skid_corpus_rarity.py runs (N>=2 PIDs).
#   Every ESV rarity Annotation carries this flag as a Phase 4/7 contract signal.
#
# KAV track — LPS-normalized severity (count / lps_count, PID-size-aware).
#   Thresholds: >15% HIGH, >5% MEDIUM, >0% LOW, ==0% NONE.
#
# AUDIENCE track — stamped on every rarity Annotation from AUDIENCE_MAP:
#   engineer_review    -> Phase 7 HITL human queue
#   pipeline_integrity -> developer health dashboard only
#   internal           -> Phase 4 FSM consumption (ESV patterns)
#
# CANARY: count=0 -> zero_expected/NONE, count>0 -> bug_signal/CRITICAL.
#
# CHANGE LOG:
#   2026-03-04  Fix _kav_severity to LPS-normalized ratio.
#               Add corpus_normalized=False to ESV rarity Annotations.
#               Replace intra-PID ESV percentile with absolute count tiers.
#               Add _fetch_lps_count() helper.
#               Import AUDIENCE_MAP from frequency_aggregation.
#               Stamp audience on all rarity Annotations.

from engine.phase3_annotation.frequency_aggregation import (
    CATEGORY_MAP,
    CANARY_PATTERNS,
    AUDIENCE_MAP,
)


_PHASE4_HINTS: dict[str, str] = {
    "pipe_junction":                   "use_as_traversal_index",
    "structural_branch":               "apply_branch_caution",
    "structural_t_junction":           "apply_branch_caution",
    "structural_high_degree":          "apply_high_caution",
    "large_manifold_node":             "apply_manifold_rules",
    "dead_end_pipe_segment":           "terminate_propagation",
    "pipe_segment_cycle_member":       "use_cycle_aware_traversal",
    "parallel_pipe_segments":          "apply_parallel_path_rules",
    "motif_ps_node_chain":             "use_as_traversal_motif",
    "rare_motif_local":                "limited_propagation_paths",
    "pipe_segment_short":              "low_confidence_segment",
    "pipe_segment_long":               "verify_segment_boundaries",
    "direction_evidence_missing":      "propagate_from_neighbour_consensus",
    "lps_direction_unresolved":        "apply_weak_prior_only",
    "direction_conflict_observed":     "apply_conflict_resolution_rule",
    "lps_weak_evidence_consensus":     "apply_reduced_confidence_seed",
    "lps_low_confidence_evidence":     "apply_confidence_weighted_propagation",
    "ps_unreachable_from_evidence":    "requires_fallback_rule_or_hitl",
    "logical_not_covered":             "skip_segment_no_physical_backing",
    "logical_missing_endpoints":       "skip_segment_no_entry_exit",
    "pipe_segment_no_logical_mapping": "skip_segment_no_logical_identity",
    "orphan_node":                     "no_action_phase7_resolves",
    "isolated_pipe_segment":           "no_action_phase7_resolves",
    "endpoint_count_mismatch":         "no_action_phase7_resolves",
    "identical_ps_neighborhood":       "no_action_phase7_resolves",
    "duplicate_symbol_candidate":      "no_action_phase7_resolves",
    "evidence_physical_only":          "no_action_phase7_resolves",
    "adjacency_metadata_mismatch":     "no_action_phase7_resolves",
    "provenance_contradiction":        "no_action_phase7_resolves",
    "endpoint_collision":              "no_action_phase7_resolves",
    "cross_pid_shared_node":           "no_action_phase7_resolves",
    "orphan_annotation":               "bug_in_phase3_ann_helper",
    "bidirectional_pipe_anomaly":      "bug_in_phase0_ingestion",
    "pipe_segment_no_evidence_via_lps":"phase4_propagation_target",
    
    # ── NEW: Engineering rule violations (Phase 3.5) ──────────────────────────
    "missing_check_valve":           "block_propagation_safety_violation",
    "missing_suction_strainer":      "reduce_confidence_unprotected_equipment",
    "missing_isolation_valve":       "no_action_phase7_resolves",
    "tank_vent_position_violation":  "no_action_phase7_resolves",
    "tank_drain_position_violation": "no_action_phase7_resolves",
    "control_valve_after_orifice":   "no_action_phase7_resolves",
    "missing_pressure_relief_valve": "block_propagation_safety_violation",
    "missing_warming_coil":          "block_propagation_safety_violation",
    "missing_cooling_jacket":        "block_propagation_safety_violation",
}

_MISSING_HINTS: frozenset = frozenset(CATEGORY_MAP) - frozenset(_PHASE4_HINTS)
if _MISSING_HINTS:
    import warnings
    warnings.warn(
        f"[RARITY] _PHASE4_HINTS missing entries for: {sorted(_MISSING_HINTS)}. "
        "Falling back to 'consult_pattern_documentation'.",
        stacklevel=2,
    )

_UNCONDITIONALLY_BLOCKED: frozenset = frozenset({
    "logical_not_covered",
    "logical_missing_endpoints",
    "pipe_segment_no_logical_mapping",
    # NEW: Safety-critical engineering violations (Phase 3.5)
    "missing_check_valve",              # Backflow prevention - critical
    "missing_pressure_relief_valve",    # Overpressure protection - critical
    "missing_warming_coil",             # Cryogenic safety - critical
    "missing_cooling_jacket",           # High-temperature safety - critical
})

_BLOCK_AT_SEVERITY: frozenset = frozenset({"HIGH", "CRITICAL"})

# Patterns that must NEVER block FSM propagation regardless of severity or hint.
# These are cross-cutting annotations resolved in Phase 7 HITL; blocking them
# cascades spurious phase4_blocked stamps onto LPS that have valid evidence.
#   cross_pid_shared_node     -- multi-PID topology, Phase 7 resolves
#   orphan_node               -- isolated node, no propagation impact
#   duplicate_symbol_candidate -- Phase 7 investigation only
_NEVER_BLOCKED: frozenset = frozenset({
    "cross_pid_shared_node",
    "orphan_node",
    "duplicate_symbol_candidate",
})


def _propagation_blocked(pattern_type, phase4_hint, hitl_severity, rarity_label):
    # Check _NEVER_BLOCKED first -- overrides all other conditions.
    if pattern_type in _NEVER_BLOCKED:
        return False
    if pattern_type in _UNCONDITIONALLY_BLOCKED:
        return True
    if phase4_hint.startswith("skip_segment"):
        return True
    if rarity_label == "bug_signal":
        return True
    if phase4_hint == "no_action_phase7_resolves" and hitl_severity in _BLOCK_AT_SEVERITY:
        return True
    return False


_KAV_HIGH_RATIO   = 0.15
_KAV_MEDIUM_RATIO = 0.05


def _kav_severity(pattern_type, count, lps_count):
    if pattern_type in CANARY_PATTERNS:
        return ("zero_expected", "NONE") if count == 0 else ("bug_signal", "CRITICAL")
    if count == 0:
        return "inactive", "NONE"
    ratio = count / max(lps_count, 1)
    if ratio > _KAV_HIGH_RATIO:
        return "priority", "HIGH"
    if ratio > _KAV_MEDIUM_RATIO:
        return "backlog", "MEDIUM"
    return "tolerable", "LOW"


_ESV_TIERS: list = [
    (0,   "absent",               0.0),
    (2,   "architecturally_rare", 0.10),
    (10,  "uncommon",             0.30),
    (30,  "typical",              0.60),
    (80,  "common",               0.85),
]
_ESV_DOMINANT = ("dominant", 0.99)


def _esv_tier(unique_target_count):
    for threshold, label, score in _ESV_TIERS:
        if unique_target_count <= threshold:
            return label, score
    return _ESV_DOMINANT


def _fetch_lps_count(session, pid_id):
    row = session.run(
        "MATCH (lps:LogicalPipeSegment {pid_id: $pid_id}) RETURN count(lps) AS c",
        pid_id=pid_id,
    ).single()
    return int(row["c"]) if row else 1


def compute_structural_rarity(session, pid_id: str) -> None:
    rows = session.run(
        """
        MATCH (freq:Annotation {pid_id: $pid_id, source: 'phase3_structural_frequencies'})
        WHERE freq.pattern_type IS NOT NULL AND freq.pattern_type <> '__summary__'
        RETURN
            freq.id                  AS freq_ann_id,
            freq.pattern_type        AS pattern_type,
            freq.category            AS category,
            freq.audience            AS audience,
            freq.is_canary           AS is_canary,
            freq.absolute_count      AS absolute_count,
            freq.unique_target_count AS unique_target_count
        """,
        pid_id=pid_id,
    ).data()

    if not rows:
        print(f"[PHASE3][RARITY] No frequency data for PID={pid_id}. Skipping.")
        return

    lps_count = _fetch_lps_count(session, pid_id)
    esv_rows  = [r for r in rows if r.get("category") == "ESV"]
    kav_rows  = [r for r in rows if r.get("category") == "KAV"]
    n_esv     = len(esv_rows)

    # ── ESV: absolute count tiers ─────────────────────────────────────────────
    for r in esv_rows:
        pt          = r["pattern_type"]
        count       = int(r["absolute_count"] or 0)
        unique      = int(r["unique_target_count"] or 0)
        freq_ann_id = r["freq_ann_id"]
        audience    = AUDIENCE_MAP.get(pt, "internal")
        label, score = _esv_tier(unique)
        phase4_hint  = _PHASE4_HINTS.get(pt, "consult_pattern_documentation")

        rarity_id = f"rarity_{pid_id}_{pt}"
        session.run(
            """
            MERGE (a:Annotation {id: $rarity_id})
            ON CREATE SET
              a.pid_id              = $pid_id,
              a.type                = 'structural_pattern_rarity',
              a.source              = 'phase3_structural_rarity',
              a.pattern_type        = $pt,
              a.category            = 'ESV',
              a.audience            = $audience,
              a.is_canary           = false,
              a.corpus_normalized   = false,
              a.rarity_label        = $label,
              a.rarity_score        = $score,
              a.percentile_rank     = null,
              a.absolute_count      = $count,
              a.unique_target_count = $unique,
              a.hitl_severity       = 'NONE',
              a.phase4_hint         = $phase4_hint,
              a.propagation_blocked = false,
              a.first_seen          = datetime()
            ON MATCH SET
              a.audience            = $audience,
              a.corpus_normalized   = false,
              a.rarity_label        = $label,
              a.rarity_score        = $score,
              a.percentile_rank     = null,
              a.absolute_count      = $count,
              a.unique_target_count = $unique,
              a.phase4_hint         = $phase4_hint,
              a.propagation_blocked = false,
              a.last_seen           = datetime()
            WITH a
            MATCH (freq:Annotation {id: $freq_ann_id})
            MERGE (a)-[:ANNOTATES]->(freq)
            """,
            rarity_id=rarity_id, pid_id=pid_id, pt=pt,
            audience=audience, label=label, score=score,
            count=count, unique=unique,
            phase4_hint=phase4_hint, freq_ann_id=freq_ann_id,
        )

    # ── KAV: LPS-normalized severity ─────────────────────────────────────────
    for r in kav_rows:
        pt           = r["pattern_type"]
        count        = int(r["absolute_count"] or 0)
        unique       = int(r["unique_target_count"] or 0)
        is_canary    = bool(r.get("is_canary", False))
        freq_ann_id  = r["freq_ann_id"]
        # AUDIENCE_MAP is the ground truth — do not trust freq annotation alone
        audience     = AUDIENCE_MAP.get(pt, "pipeline_integrity")

        label, hitl_severity = _kav_severity(pt, count, lps_count)
        phase4_hint          = _PHASE4_HINTS.get(pt, "no_action_phase7_resolves")
        normalized_ratio     = round(count / max(lps_count, 1), 4)

        if label == "bug_signal":
            rarity_score = 0.0
        elif count == 0:
            rarity_score = 1.0
        else:
            rarity_score = round(max(0.01, 1.0 - normalized_ratio * 4), 4)

        blocked = _propagation_blocked(pt, phase4_hint, hitl_severity, label)

        rarity_id = f"rarity_{pid_id}_{pt}"
        session.run(
            """
            MERGE (a:Annotation {id: $rarity_id})
            ON CREATE SET
              a.pid_id              = $pid_id,
              a.type                = 'structural_pattern_rarity',
              a.source              = 'phase3_structural_rarity',
              a.pattern_type        = $pt,
              a.category            = 'KAV',
              a.audience            = $audience,
              a.is_canary           = $is_canary,
              a.corpus_normalized   = true,
              a.rarity_label        = $label,
              a.rarity_score        = $score,
              a.percentile_rank     = null,
              a.absolute_count      = $count,
              a.unique_target_count = $unique,
              a.normalized_ratio    = $normalized_ratio,
              a.lps_count           = $lps_count,
              a.hitl_severity       = $hitl_severity,
              a.phase4_hint         = $phase4_hint,
              a.propagation_blocked = $blocked,
              a.first_seen          = datetime()
            ON MATCH SET
              a.audience            = $audience,
              a.corpus_normalized   = true,
              a.rarity_label        = $label,
              a.rarity_score        = $score,
              a.absolute_count      = $count,
              a.unique_target_count = $unique,
              a.normalized_ratio    = $normalized_ratio,
              a.lps_count           = $lps_count,
              a.hitl_severity       = $hitl_severity,
              a.phase4_hint         = $phase4_hint,
              a.propagation_blocked = $blocked,
              a.last_seen           = datetime()
            WITH a
            MATCH (freq:Annotation {id: $freq_ann_id})
            MERGE (a)-[:ANNOTATES]->(freq)
            """,
            rarity_id=rarity_id, pid_id=pid_id, pt=pt,
            audience=audience, label=label, score=rarity_score,
            count=count, unique=unique, is_canary=is_canary,
            normalized_ratio=normalized_ratio, lps_count=lps_count,
            hitl_severity=hitl_severity, phase4_hint=phase4_hint,
            blocked=blocked, freq_ann_id=freq_ann_id,
        )

    # ── Summary ────────────────────────────────────────────────────────────────
    def _sev(r):
        return _kav_severity(r["pattern_type"], int(r.get("absolute_count") or 0), lps_count)

    critical = sum(1 for r in kav_rows if _sev(r)[1] == "CRITICAL")
    high     = sum(1 for r in kav_rows if _sev(r)[1] == "HIGH")
    blocked_count = sum(
        1 for r in kav_rows
        if _propagation_blocked(
            r["pattern_type"],
            _PHASE4_HINTS.get(r["pattern_type"], "no_action_phase7_resolves"),
            _sev(r)[1], _sev(r)[0],
        )
    )
    er_high = sum(
        1 for r in kav_rows
        if AUDIENCE_MAP.get(r["pattern_type"]) == "engineer_review"
        and _sev(r)[1] in {"HIGH", "CRITICAL"}
    )

    print(
        f"[PHASE3][RARITY] Rarity scoring complete for PID={pid_id}: "
        f"{n_esv} ESV patterns scored (absolute tiers, corpus_normalized=False), "
        f"{len(kav_rows)} KAV patterns scored "
        f"(LPS-normalized, lps_count={lps_count}) "
        f"[CRITICAL={critical}, HIGH={high}, "
        f"engineer_review_HIGH={er_high}, "
        f"PROPAGATION_BLOCKED={blocked_count}]."
    )