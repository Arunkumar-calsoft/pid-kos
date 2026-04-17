# engine/phase3_annotation/skid_corpus_rarity.py
#
# Per-Skid Corpus Builder — Cross-PID ESV rarity normalization
#
# DIAGRAM COMPONENT: "Per-Skid Corpus" (p9)
# DIAGRAM FLOWS:
#   Phase 3 → Per-Skid Corpus (C16)
#   Global Registry → Per-Skid Corpus (C17)
#
# PURPOSE:
#   Collects ESV frequency data from ALL PIDs in a skid and recomputes
#   rarity scores using cross-PID percentile-based tiers instead of per-PID
#   absolute-count tiers.  Sets corpus_normalized=True on updated Annotations.
#
# PREREQUISITES:
#   At least 2 PIDs in the target skid must have status >= PHASE3_COMPLETE.
#   Per-PID rarity scoring (compute_structural_rarity) must have run on each.
#
# HOW IT WORKS:
#   1. Read all ESV frequency Annotations across all PIDs in the skid.
#   2. For each ESV pattern_type, compute:
#      - corpus_mean:     mean unique_target_count across PIDs
#      - corpus_std:      standard deviation
#      - corpus_total:    sum of absolute_count across all PIDs
#      - corpus_pid_count: number of PIDs contributing data
#   3. Compute the percentile rank of each PID's unique_target_count within
#      the corpus distribution for that pattern.
#   4. Recompute rarity using corpus-aware percentile tiers:
#      - ≤ 5th percentile: "corpus_rare"       (score=0.10)
#      - ≤ 25th:           "corpus_uncommon"    (score=0.30)
#      - ≤ 75th:           "corpus_typical"     (score=0.60)
#      - ≤ 95th:           "corpus_common"      (score=0.85)
#      - > 95th:           "corpus_dominant"    (score=0.99)
#   5. Update the rarity Annotation in Neo4j:
#      - corpus_normalized=True
#      - rarity_label=<new label>
#      - rarity_score=<new score>
#      - percentile_rank=<computed percentile>
#      - corpus_mean, corpus_std, corpus_total, corpus_pid_count
#   6. Create a SkidCorpus node summarising the cross-PID aggregation.
#
# RESULT:
#   ESV rarity Annotations transition from:
#     corpus_normalized=False (absolute tiers, per-PID)
#   to:
#     corpus_normalized=True  (percentile tiers, cross-PID)

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Tuple


# ── Corpus-aware percentile tiers ─────────────────────────────────────────────

_CORPUS_TIERS: list = [
    (0.05, "corpus_rare",     0.10),
    (0.25, "corpus_uncommon", 0.30),
    (0.75, "corpus_typical",  0.60),
    (0.95, "corpus_common",   0.85),
]
_CORPUS_DOMINANT = ("corpus_dominant", 0.99)


def _corpus_tier(percentile: float) -> Tuple[str, float]:
    for threshold, label, score in _CORPUS_TIERS:
        if percentile <= threshold:
            return label, score
    return _CORPUS_DOMINANT


def _percentile_rank(value: float, sorted_values: List[float]) -> float:
    """Compute the percentile rank of value within sorted_values (0.0–1.0)."""
    n = len(sorted_values)
    if n <= 1:
        return 0.5
    count_below = sum(1 for v in sorted_values if v < value)
    count_equal = sum(1 for v in sorted_values if v == value)
    return (count_below + 0.5 * count_equal) / n


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

def build_skid_corpus(session, skid_id: str) -> Dict:
    """
    Build the Per-Skid Corpus by aggregating ESV rarity across all PIDs
    in the given skid.

    Returns a summary dict with corpus statistics.
    """

    # Step 1: Find all PIDs in this skid with at least PHASE3_COMPLETE
    pids = session.run(
        """
        MATCH (skid:Skid {skid_id: $skid_id})-[:HAS_PID]->(pid:PID)
        WHERE pid.status IN [
            'PHASE3_COMPLETE', 'PHASE4_COMPLETE', 'PHASE5_COMPLETE',
            'PHASE6_COMPLETE', 'PHASE7_COMPLETE'
        ]
        RETURN pid.pid_id AS pid_id
        ORDER BY pid.pid_id
        """,
        skid_id=skid_id,
    ).data()

    pid_ids = [r["pid_id"] for r in pids]
    if len(pid_ids) < 2:
        print(
            f"[CORPUS] Skid={skid_id}: only {len(pid_ids)} PID(s) available. "
            f"Need ≥2 for corpus normalization. Skipping."
        )
        return {"skid_id": skid_id, "pid_count": len(pid_ids), "skipped": True}

    print(f"[CORPUS] Skid={skid_id}: {len(pid_ids)} PIDs → {pid_ids}")

    # Step 2: Collect ESV frequency data across all PIDs
    # pattern_type → list of (pid_id, unique_target_count, absolute_count, freq_ann_id)
    pattern_data: Dict[str, List[dict]] = defaultdict(list)

    for pid_id in pid_ids:
        rows = session.run(
            """
            MATCH (freq:Annotation {
                pid_id: $pid_id,
                source: 'phase3_structural_frequencies',
                category: 'ESV'
            })
            WHERE freq.pattern_type IS NOT NULL
              AND freq.pattern_type <> '__summary__'
            RETURN
                freq.id                  AS freq_ann_id,
                freq.pattern_type        AS pattern_type,
                freq.absolute_count      AS absolute_count,
                freq.unique_target_count AS unique_target_count
            """,
            pid_id=pid_id,
        ).data()

        for r in rows:
            pattern_data[r["pattern_type"]].append({
                "pid_id": pid_id,
                "unique_target_count": int(r["unique_target_count"] or 0),
                "absolute_count": int(r["absolute_count"] or 0),
                "freq_ann_id": r["freq_ann_id"],
            })

    # Step 3: Compute corpus statistics per pattern and update rarity Annotations
    patterns_updated = 0
    annotations_updated = 0

    for pattern_type, entries in sorted(pattern_data.items()):
        unique_counts = [e["unique_target_count"] for e in entries]
        absolute_counts = [e["absolute_count"] for e in entries]
        sorted_unique = sorted(unique_counts)

        corpus_mean, corpus_std = _mean_std(unique_counts)
        corpus_total = sum(absolute_counts)
        corpus_pid_count = len(entries)

        for entry in entries:
            percentile = _percentile_rank(
                entry["unique_target_count"], sorted_unique
            )
            label, score = _corpus_tier(percentile)

            rarity_id = f"rarity_{entry['pid_id']}_{pattern_type}"
            session.run(
                """
                MATCH (a:Annotation {id: $rarity_id})
                SET a.corpus_normalized = true,
                    a.rarity_label      = $label,
                    a.rarity_score      = $score,
                    a.percentile_rank   = $percentile,
                    a.corpus_mean       = $corpus_mean,
                    a.corpus_std        = $corpus_std,
                    a.corpus_total      = $corpus_total,
                    a.corpus_pid_count  = $corpus_pid_count,
                    a.corpus_updated_at = datetime()
                """,
                rarity_id=rarity_id,
                label=label, score=score,
                percentile=round(percentile, 4),
                corpus_mean=round(corpus_mean, 4),
                corpus_std=round(corpus_std, 4),
                corpus_total=corpus_total,
                corpus_pid_count=corpus_pid_count,
            )
            annotations_updated += 1

        patterns_updated += 1

    # Step 4: Create/update SkidCorpus summary node
    corpus_id = f"corpus_{skid_id}"
    session.run(
        """
        MERGE (c:SkidCorpus {id: $corpus_id})
        ON CREATE SET
            c.skid_id        = $skid_id,
            c.pid_count      = $pid_count,
            c.pattern_count  = $pattern_count,
            c.annotations_updated = $ann_updated,
            c.created_at     = datetime()
        ON MATCH SET
            c.pid_count      = $pid_count,
            c.pattern_count  = $pattern_count,
            c.annotations_updated = $ann_updated,
            c.updated_at     = datetime()
        WITH c
        MATCH (skid:Skid {skid_id: $skid_id})
        MERGE (c)-[:CORPUS_OF]->(skid)
        """,
        corpus_id=corpus_id, skid_id=skid_id,
        pid_count=len(pid_ids), pattern_count=patterns_updated,
        ann_updated=annotations_updated,
    )

    summary = {
        "skid_id": skid_id,
        "pid_count": len(pid_ids),
        "pid_ids": pid_ids,
        "patterns_updated": patterns_updated,
        "annotations_updated": annotations_updated,
        "skipped": False,
    }

    print(
        f"[CORPUS] Skid={skid_id}: corpus built — "
        f"{patterns_updated} ESV patterns normalized across {len(pid_ids)} PIDs, "
        f"{annotations_updated} rarity Annotations updated (corpus_normalized=True)."
    )

    return summary
