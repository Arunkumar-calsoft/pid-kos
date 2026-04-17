# engine/phase3_annotation/global_statistics.py
#
# Global Statistical Knowledge Layer — Cross-skid frequency & rarity aggregation
#
# DIAGRAM COMPONENT: "Global Statistical Knowledge Layer" (p10)
#   "Validated pattern frequencies & rarity distributions"
#
# DIAGRAM FLOWS:
#   Per-Skid Corpus → Global Statistical Knowledge Layer (C18)
#   Global Statistical Knowledge Layer → Phase 4 (C19)
#
# PURPOSE:
#   Aggregates pattern frequency data across ALL skids in the plant to produce
#   a global baseline of "normal" pattern distributions.  Phase 4 FSM consults
#   these global statistics when seeding flow confidence:
#     - Patterns that are globally rare get boosted confidence (strong signal)
#     - Patterns that are globally common get reduced impact (noise)
#
# PREREQUISITES:
#   Per-Skid Corpus (skid_corpus_rarity.py) must have run on ≥1 skid.
#   Each participating skid must have ≥2 PIDs with PHASE3_COMPLETE.
#
# DATA MODEL:
#   Creates GlobalStatistic nodes in Neo4j:
#     (:GlobalStatistic {
#       id:               "gstat_<pattern_type>",
#       pattern_type:     str,
#       category:         "ESV",
#       global_mean:      float,   # mean unique_target_count across all PIDs
#       global_std:       float,   # standard deviation
#       global_total:     int,     # sum of absolute_count
#       global_pid_count: int,     # number of PIDs contributing
#       skid_count:       int,     # number of skids contributing
#       global_rarity:    str,     # tier label based on frequency
#       updated_at:       datetime
#     })
#
#   Phase 4 can query GlobalStatistic to adjust seed confidence:
#     MATCH (gs:GlobalStatistic {pattern_type: $pt})
#     RETURN gs.global_rarity, gs.global_mean
#
# OUTPUT:
#   - GlobalStatistic nodes (one per ESV pattern)
#   - GlobalStatisticsSummary node with top-level aggregation

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Tuple


# ── Global rarity tier (based on cross-skid frequency) ────────────────────────

_GLOBAL_TIERS: list = [
    (2,   "globally_absent",  0.05),
    (5,   "globally_rare",    0.15),
    (20,  "globally_uncommon", 0.35),
    (50,  "globally_typical",  0.60),
    (100, "globally_common",   0.85),
]
_GLOBAL_DOMINANT = ("globally_dominant", 0.95)


def _global_tier(total_count: int) -> Tuple[str, float]:
    for threshold, label, score in _GLOBAL_TIERS:
        if total_count <= threshold:
            return label, score
    return _GLOBAL_DOMINANT


def _mean_std(values: List[float]) -> Tuple[float, float]:
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    if n == 1:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, math.sqrt(variance)


# ── Main entry point ──────────────────────────────────────────────────────────

def build_global_statistics(session, plant_id: str) -> Dict:
    """
    Build the Global Statistical Knowledge Layer by aggregating ESV frequency
    data across all skids in the plant.

    Args:
        session: Neo4j session
        plant_id: Plant ID to aggregate across

    Returns:
        Summary dict with global statistics.
    """

    # Step 1: Collect ESV frequency data from all PIDs in the plant
    rows = session.run(
        """
        MATCH (plant:Plant {plant_id: $plant_id})
              -[:HAS_SKID]->(skid:Skid)
              -[:HAS_PID]->(pid:PID)
        MATCH (freq:Annotation {
            pid_id: pid.pid_id,
            source: 'phase3_structural_frequencies',
            category: 'ESV'
        })
        WHERE freq.pattern_type IS NOT NULL
          AND freq.pattern_type <> '__summary__'
        RETURN
            skid.skid_id             AS skid_id,
            pid.pid_id               AS pid_id,
            freq.pattern_type        AS pattern_type,
            freq.absolute_count      AS absolute_count,
            freq.unique_target_count AS unique_target_count
        """,
        plant_id=plant_id,
    ).data()

    if not rows:
        print(
            f"[GLOBAL_STATS] Plant={plant_id}: no ESV frequency data found. "
            "Run Phase 3 on at least one PID first."
        )
        return {"plant_id": plant_id, "skipped": True, "reason": "no_data"}

    # Step 2: Aggregate by pattern_type
    # pattern_type → list of {skid_id, pid_id, unique_target_count, absolute_count}
    pattern_data: Dict[str, List[dict]] = defaultdict(list)
    skid_set = set()

    for r in rows:
        pattern_data[r["pattern_type"]].append({
            "skid_id": r["skid_id"],
            "pid_id": r["pid_id"],
            "unique_target_count": int(r["unique_target_count"] or 0),
            "absolute_count": int(r["absolute_count"] or 0),
        })
        skid_set.add(r["skid_id"])

    total_pids = len({r["pid_id"] for r in rows})

    # Step 3: Create GlobalStatistic nodes
    patterns_created = 0

    for pattern_type, entries in sorted(pattern_data.items()):
        unique_counts = [e["unique_target_count"] for e in entries]
        absolute_counts = [e["absolute_count"] for e in entries]

        global_mean, global_std = _mean_std(unique_counts)
        global_total = sum(absolute_counts)
        global_pid_count = len(entries)
        skid_count = len({e["skid_id"] for e in entries})

        rarity_label, rarity_score = _global_tier(global_total)

        gstat_id = f"gstat_{pattern_type}"
        session.run(
            """
            MERGE (gs:GlobalStatistic {id: $gstat_id})
            ON CREATE SET
                gs.pattern_type    = $pattern_type,
                gs.category        = 'ESV',
                gs.plant_id        = $plant_id,
                gs.global_mean     = $global_mean,
                gs.global_std      = $global_std,
                gs.global_total    = $global_total,
                gs.global_pid_count = $global_pid_count,
                gs.skid_count      = $skid_count,
                gs.global_rarity   = $rarity_label,
                gs.global_rarity_score = $rarity_score,
                gs.created_at      = datetime()
            ON MATCH SET
                gs.plant_id        = $plant_id,
                gs.global_mean     = $global_mean,
                gs.global_std      = $global_std,
                gs.global_total    = $global_total,
                gs.global_pid_count = $global_pid_count,
                gs.skid_count      = $skid_count,
                gs.global_rarity   = $rarity_label,
                gs.global_rarity_score = $rarity_score,
                gs.updated_at      = datetime()
            WITH gs
            MATCH (plant:Plant {plant_id: $plant_id})
            MERGE (gs)-[:STATISTICS_OF]->(plant)
            """,
            gstat_id=gstat_id, pattern_type=pattern_type,
            plant_id=plant_id,
            global_mean=round(global_mean, 4),
            global_std=round(global_std, 4),
            global_total=global_total,
            global_pid_count=global_pid_count,
            skid_count=skid_count,
            rarity_label=rarity_label, rarity_score=rarity_score,
        )
        patterns_created += 1

    # Step 4: Create/update GlobalStatisticsSummary
    summary_id = f"gstat_summary_{plant_id}"
    session.run(
        """
        MERGE (gs:GlobalStatisticsSummary {id: $summary_id})
        ON CREATE SET
            gs.plant_id       = $plant_id,
            gs.pattern_count  = $pattern_count,
            gs.total_pids     = $total_pids,
            gs.total_skids    = $total_skids,
            gs.created_at     = datetime()
        ON MATCH SET
            gs.pattern_count  = $pattern_count,
            gs.total_pids     = $total_pids,
            gs.total_skids    = $total_skids,
            gs.updated_at     = datetime()
        WITH gs
        MATCH (plant:Plant {plant_id: $plant_id})
        MERGE (gs)-[:SUMMARY_OF]->(plant)
        """,
        summary_id=summary_id, plant_id=plant_id,
        pattern_count=patterns_created,
        total_pids=total_pids,
        total_skids=len(skid_set),
    )

    summary = {
        "plant_id": plant_id,
        "skipped": False,
        "patterns_created": patterns_created,
        "total_pids": total_pids,
        "total_skids": len(skid_set),
        "skid_ids": sorted(skid_set),
    }

    print(
        f"[GLOBAL_STATS] Plant={plant_id}: global statistics built — "
        f"{patterns_created} ESV patterns aggregated across "
        f"{total_pids} PIDs in {len(skid_set)} skid(s)."
    )

    return summary
