"""
Demo: shows the full pattern -> frequency -> rarity -> Phase 4 chain.
Run: python tests/demo_rarity_chain.py
"""
from neo4j import GraphDatabase

driver = GraphDatabase.driver("neo4j://localhost:7687", auth=("neo4j", "awesomepassword.0"))

with driver.session(database="chatbot") as s:

    # ── 1. Pattern chain ──────────────────────────────────────────────────────
    print("=" * 70)
    print("CHAIN: pattern_detection -> frequency -> rarity -> phase4_hint")
    print("=" * 70)
    rows = s.run("""
        MATCH (freq:Annotation {source:'phase3_structural_frequencies'})
        WHERE freq.pattern_type IS NOT NULL AND freq.pattern_type <> '__summary__'
        OPTIONAL MATCH (rar:Annotation {source:'phase3_structural_rarity',
                                        pattern_type: freq.pattern_type})
        RETURN freq.pattern_type        AS pattern,
               freq.category            AS cat,
               freq.absolute_count      AS count,
               rar.rarity_label         AS rarity_label,
               rar.hitl_severity        AS severity,
               rar.propagation_blocked  AS blocked,
               rar.phase4_hint          AS phase4_hint
        ORDER BY freq.category, freq.absolute_count DESC
    """).data()

    print(f"  Patterns tracked: {len(rows)}")
    print()
    print(f"  {'PATTERN':<46} {'CAT':<4} {'CNT':<6} {'RARITY_LABEL':<22} {'SEVERITY':<10} PHASE4_HINT")
    print(f"  {'-'*46} {'-'*4} {'-'*6} {'-'*22} {'-'*10} {'-'*30}")
    for r in rows:
        print(
            f"  {str(r['pattern']):<46} "
            f"{str(r['cat']):<4} "
            f"{str(r['count']):<6} "
            f"{str(r['rarity_label']):<22} "
            f"{str(r['severity']):<10} "
            f"{str(r['phase4_hint'])}"
        )

    print()

    # ── 2. Phase 4 effects ────────────────────────────────────────────────────
    print("=" * 70)
    print("PHASE 4 EFFECTS")
    print("=" * 70)

    def _q(query: str) -> int:
        row = s.run(query)  # type: ignore[arg-type]
        rec = row.single()
        return int(rec["c"]) if rec is not None else 0

    blocked     = _q("MATCH (lps:LogicalPipeSegment) WHERE lps.phase4_blocked = true RETURN count(lps) AS c")
    print(f"  LPS with phase4_blocked=true  (flow propagation stopped): {blocked}")

    eng_blocked = _q("MATCH (lps:LogicalPipeSegment) WHERE lps.phase4_hint = 'block_propagation_safety_violation' RETURN count(lps) AS c")
    print(f"  LPS blocked by engineering rule violation:                {eng_blocked}")

    boosted     = _q("MATCH (lps:LogicalPipeSegment) WHERE lps.global_rarity_boost = true RETURN count(lps) AS c")
    print(f"  LPS with global_rarity_boost (+25%% seed confidence):     {boosted}")

    reduced     = _q("MATCH (lps:LogicalPipeSegment) WHERE lps.global_rarity_reduced = true RETURN count(lps) AS c")
    print(f"  LPS with global_rarity_reduced (-15%% seed confidence):   {reduced}")

    total_lps   = _q("MATCH (lps:LogicalPipeSegment) RETURN count(lps) AS c")
    print(f"  Total LPS:                                                {total_lps}")

    print()

    # ── 3. Corpus status ──────────────────────────────────────────────────────
    print("=" * 70)
    print("CORPUS STATUS")
    print("=" * 70)

    gs_count  = _q("MATCH (gs:GlobalStatistic) RETURN count(gs) AS c")
    pid_count = _q("MATCH (p:PID) RETURN count(p) AS c")

    print(f"  PIDs in plant:           {pid_count}")
    print(f"  GlobalStatistic nodes:   {gs_count}")
    if gs_count == 0:
        print("  Cross-PID layer:         DORMANT (no GlobalStatistic nodes)")
        print("  Phase 4 global boost:    SKIPPED (guarded by has_global==0 check)")
        print("  Per-PID rarity blocks:   ACTIVE (works on any single drawing)")
    else:
        print("  Cross-PID layer:         ACTIVE")

    print()

    # ── 4. HITL queue preview ─────────────────────────────────────────────────
    print("=" * 70)
    print("HITL REVIEW QUEUE (rarity-sourced, HIGH/CRITICAL)")
    print("=" * 70)
    hitl_rows = s.run("""
        MATCH (a:Annotation {type:'structural_pattern_rarity', category:'KAV'})
        WHERE a.hitl_severity IN ['HIGH', 'CRITICAL']
        RETURN a.pid_id AS pid, a.pattern_type AS pattern,
               a.hitl_severity AS severity, a.rarity_label AS label
        ORDER BY a.hitl_severity, a.pid_id
    """).data()
    if hitl_rows:
        for r in hitl_rows:
            print(f"  [{r['severity']}] {r['pid']} | {r['pattern']} | {r['label']}")
    else:
        print("  No HIGH/CRITICAL KAV rarity items queued.")

driver.close()
print()
print("Done.")
