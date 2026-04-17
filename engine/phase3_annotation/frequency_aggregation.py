# engine/phase3_annotation/frequency_aggregation.py
#
# Phase 3 — Structural frequency aggregation (pid-scoped)
#
# GAP-1 FIX (_COUNTED_SOURCES):
#   'phase3_engineering_rules' added to _COUNTED_SOURCES.
#   Engineering rule violation Annotations (source='phase3_engineering_rules')
#   were silently excluded from all frequency counting, rarity scoring, and
#   Phase 7 HITL queue sizing.  The nine CATEGORY_MAP / AUDIENCE_MAP entries
#   added for Phase 3.5 patterns (missing_check_valve, missing_pressure_relief_valve,
#   etc.) were dead code because the frequency query filtered on source and
#   'phase3_engineering_rules' was not in the allowed set.
#   Adding it here makes Phase 3.5 violations visible to the full downstream chain.

# ── Pattern taxonomy ──────────────────────────────────────────────────────────

CATEGORY_MAP: dict[str, str] = {
    # ── ESV — Engineering Structure Value ─────────────────────────────────────
    "structural_branch":               "ESV",
    "structural_t_junction":           "ESV",
    "structural_high_degree":          "ESV",
    "dead_end_pipe_segment":           "ESV",
    "pipe_segment_cycle_member":       "ESV",
    "parallel_pipe_segments":          "ESV",
    "pipe_junction":                   "ESV",
    "pipe_segment_short":              "ESV",
    "pipe_segment_long":               "ESV",
    "motif_ps_node_chain":             "ESV",
    "large_manifold_node":             "ESV",
    "rare_motif_local":                "ESV",

    # ── KAV — Knowledge Architecture Validity ─────────────────────────────────
    "orphan_node":                     "KAV",
    "isolated_pipe_segment":           "KAV",
    "logical_not_covered":             "KAV",
    "pipe_segment_no_logical_mapping": "KAV",
    "endpoint_count_mismatch":         "KAV",
    "logical_missing_endpoints":       "KAV",
    "direction_conflict_observed":     "KAV",
    "lps_direction_unresolved":        "KAV",
    "pipe_segment_no_evidence_via_lps":"KAV",
    "identical_ps_neighborhood":       "KAV",
    "duplicate_symbol_candidate":      "KAV",
    "evidence_physical_only":          "KAV",
    "bidirectional_pipe_anomaly":      "KAV",
    "adjacency_metadata_mismatch":     "KAV",
    "orphan_annotation":               "KAV",
    "provenance_contradiction":        "KAV",
    "endpoint_collision":              "KAV",
    "lps_weak_evidence_consensus":     "KAV",
    "lps_low_confidence_evidence":     "KAV",
    "ps_unreachable_from_evidence":    "KAV",
    "cross_pid_shared_node":           "KAV",
    "direction_evidence_missing":      "KAV",

    # ── Phase 3.5 Engineering rule violations ─────────────────────────────────
    "missing_check_valve":             "KAV",
    "missing_suction_strainer":        "KAV",
    "missing_isolation_valve":         "KAV",
    "tank_vent_position_violation":    "KAV",
    "tank_drain_position_violation":   "KAV",
    "control_valve_after_orifice":     "KAV",
    "missing_pressure_relief_valve":   "KAV",
    "missing_warming_coil":            "KAV",
    "missing_cooling_jacket":          "KAV",
}

CANARY_PATTERNS: frozenset[str] = frozenset({
    "orphan_annotation",
    "bidirectional_pipe_anomaly",
})

AUDIENCE_MAP: dict[str, str] = {
    # ── ESV: consumed by Phase 4 FSM ──────────────────────────────────────────
    "structural_branch":               "internal",
    "structural_t_junction":           "internal",
    "structural_high_degree":          "internal",
    "dead_end_pipe_segment":           "internal",
    "pipe_segment_cycle_member":       "internal",
    "parallel_pipe_segments":          "internal",
    "pipe_junction":                   "internal",
    "pipe_segment_short":              "internal",
    "pipe_segment_long":               "internal",
    "motif_ps_node_chain":             "internal",
    "large_manifold_node":             "internal",
    "rare_motif_local":                "internal",

    # ── KAV: engineer_review ──────────────────────────────────────────────────
    "direction_evidence_missing":      "engineer_review",
    "direction_conflict_observed":     "engineer_review",
    "lps_direction_unresolved":        "engineer_review",
    "lps_weak_evidence_consensus":     "engineer_review",
    "lps_low_confidence_evidence":     "engineer_review",
    "orphan_node":                     "engineer_review",
    "duplicate_symbol_candidate":      "engineer_review",
    "cross_pid_shared_node":           "engineer_review",

    # ── Phase 3.5 violations → engineer_review ────────────────────────────────
    "missing_check_valve":             "engineer_review",
    "missing_suction_strainer":        "engineer_review",
    "missing_isolation_valve":         "engineer_review",
    "tank_vent_position_violation":    "engineer_review",
    "tank_drain_position_violation":   "engineer_review",
    "control_valve_after_orifice":     "engineer_review",
    "missing_pressure_relief_valve":   "engineer_review",
    "missing_warming_coil":            "engineer_review",
    "missing_cooling_jacket":          "engineer_review",

    # ── KAV: pipeline_integrity ───────────────────────────────────────────────
    "isolated_pipe_segment":           "pipeline_integrity",
    "logical_not_covered":             "pipeline_integrity",
    "pipe_segment_no_logical_mapping": "pipeline_integrity",
    "endpoint_count_mismatch":         "pipeline_integrity",
    "logical_missing_endpoints":       "pipeline_integrity",
    "pipe_segment_no_evidence_via_lps":"pipeline_integrity",
    "identical_ps_neighborhood":       "pipeline_integrity",
    "evidence_physical_only":          "pipeline_integrity",
    "adjacency_metadata_mismatch":     "pipeline_integrity",
    "provenance_contradiction":        "pipeline_integrity",
    "endpoint_collision":              "pipeline_integrity",
    "ps_unreachable_from_evidence":    "pipeline_integrity",
    "orphan_annotation":               "pipeline_integrity",
    "bidirectional_pipe_anomaly":      "pipeline_integrity",
}

# ── Safety contract ───────────────────────────────────────────────────────────

_MISSING_AUDIENCE: frozenset[str] = frozenset(CATEGORY_MAP) - frozenset(AUDIENCE_MAP)
if _MISSING_AUDIENCE:
    raise RuntimeError(
        f"[TAXONOMY ERROR] AUDIENCE_MAP is missing entries for: "
        f"{sorted(_MISSING_AUDIENCE)}. "
        f"Add audience classification to frequency_aggregation.py before running Phase 3."
    )

_EXTRA_AUDIENCE: frozenset[str] = frozenset(AUDIENCE_MAP) - frozenset(CATEGORY_MAP)
if _EXTRA_AUDIENCE:
    raise RuntimeError(
        f"[TAXONOMY ERROR] AUDIENCE_MAP has entries not in CATEGORY_MAP: "
        f"{sorted(_EXTRA_AUDIENCE)}. "
        f"Remove stale entries from AUDIENCE_MAP in frequency_aggregation.py."
    )


# ── Annotation sources included in the frequency count ────────────────────────
#
# GAP-1 FIX: 'phase3_engineering_rules' added.
# Previously only phase3_structural_patterns and phase3_gap_detection were counted.
# Phase 3.5 engineering rule violation annotations have source='phase3_engineering_rules'
# and were silently excluded, making all nine Phase 3.5 KAV patterns invisible to
# frequency aggregation, rarity scoring, and Phase 7 HITL queue sizing.

_COUNTED_SOURCES: frozenset[str] = frozenset({
    "phase3_structural_patterns",
    # phase3_gap_detection removed: direction_evidence_missing is no longer an
    # Annotation node — gaps are tracked via lps.phase4_hint directly.
    "phase3_engineering_rules",     # GAP-1 FIX: Phase 3.5 violations now counted
})

_EXCLUDED_TYPES: frozenset[str] = frozenset({
    "direction_observation",
    "direction_frequency_summary",
    "structural_pattern_frequency",
    "structural_pattern_rarity",
})


def compute_structural_frequencies(session, pid_id: str) -> None:
    """
    Aggregate structural, gap-detection, and engineering-rule pattern counts
    for this pid_id.

    For each distinct pattern_type detected in this PID, creates an Annotation
    node (source='phase3_structural_frequencies') with:
      - absolute_count, unique_target_count
      - category (ESV | KAV), audience, is_canary

    Also creates a per-PID totals summary node with esv_total, kav_total,
    engineer_review_count, pipeline_integrity_count for Phase 7 queue sizing.
    """
    rows = session.run(
        """
        MATCH (a:Annotation {pid_id: $pid_id})
        WHERE a.source IN $sources
          AND a.pattern_type IS NOT NULL
          AND NOT (a.type IN $excluded_types)
        OPTIONAL MATCH (a)-[:ANNOTATES]->(target)
        WITH a.pattern_type              AS pattern_type,
             count(a)                    AS absolute_count,
             count(DISTINCT target)      AS unique_target_count
        RETURN pattern_type, absolute_count, unique_target_count
        ORDER BY absolute_count DESC
        """,
        pid_id=pid_id,
        sources=list(_COUNTED_SOURCES),
        excluded_types=list(_EXCLUDED_TYPES),
    ).data()

    esv_total                = 0
    kav_total                = 0
    esv_types                = 0
    kav_types                = 0
    engineer_review_count    = 0
    pipeline_integrity_count = 0

    for r in rows:
        pt        = r["pattern_type"]
        count     = int(r["absolute_count"])
        unique    = int(r["unique_target_count"])
        category  = CATEGORY_MAP.get(pt, "UNKNOWN")
        audience  = AUDIENCE_MAP.get(pt, "pipeline_integrity")
        is_canary = pt in CANARY_PATTERNS
        ann_id    = f"freq_{pid_id}_{pt}"

        if category == "ESV":
            esv_total += count
            esv_types += 1
        elif category == "KAV":
            kav_total += count
            kav_types += 1
            if audience == "engineer_review":
                engineer_review_count += count
            elif audience == "pipeline_integrity":
                pipeline_integrity_count += count

        session.run(
            """
            MERGE (a:Annotation {id: $ann_id})
            ON CREATE SET
              a.pid_id              = $pid_id,
              a.pattern_type        = $pt,
              a.category            = $category,
              a.audience            = $audience,
              a.is_canary           = $is_canary,
              a.absolute_count      = $count,
              a.unique_target_count = $unique,
              a.type                = 'structural_pattern_frequency',
              a.source              = 'phase3_structural_frequencies',
              a.first_seen          = datetime()
            ON MATCH SET
              a.pid_id              = $pid_id,
              a.category            = $category,
              a.audience            = $audience,
              a.is_canary           = $is_canary,
              a.absolute_count      = $count,
              a.unique_target_count = $unique,
              a.last_seen           = datetime()
            """,
            ann_id=ann_id, pid_id=pid_id, pt=pt,
            category=category, audience=audience,
            is_canary=is_canary, count=count, unique=unique,
        )

    summary_id = f"freq_summary_{pid_id}"
    session.run(
        """
        MERGE (a:Annotation {id: $summary_id})
        ON CREATE SET
          a.pid_id                   = $pid_id,
          a.type                     = 'structural_pattern_frequency',
          a.source                   = 'phase3_structural_frequencies',
          a.pattern_type             = '__summary__',
          a.esv_total                = $esv_total,
          a.kav_total                = $kav_total,
          a.esv_types                = $esv_types,
          a.kav_types                = $kav_types,
          a.total_types              = $total_types,
          a.engineer_review_count    = $er_count,
          a.pipeline_integrity_count = $pi_count,
          a.first_seen               = datetime()
        ON MATCH SET
          a.esv_total                = $esv_total,
          a.kav_total                = $kav_total,
          a.esv_types                = $esv_types,
          a.kav_types                = $kav_types,
          a.total_types              = $total_types,
          a.engineer_review_count    = $er_count,
          a.pipeline_integrity_count = $pi_count,
          a.last_seen                = datetime()
        WITH a
        MATCH (pid:PID {pid_id: $pid_id})
        MERGE (a)-[:ANNOTATES]->(pid)
        """,
        summary_id=summary_id, pid_id=pid_id,
        esv_total=esv_total, kav_total=kav_total,
        esv_types=esv_types, kav_types=kav_types,
        total_types=len(rows),
        er_count=engineer_review_count,
        pi_count=pipeline_integrity_count,
    )

    print(
        f"[PHASE3][FREQ] Frequency aggregation complete for PID={pid_id}: "
        f"{esv_types} ESV types ({esv_total} annotations), "
        f"{kav_types} KAV types ({kav_total} annotations) "
        f"[engineer_review={engineer_review_count}, "
        f"pipeline_integrity={pipeline_integrity_count}]."
    )