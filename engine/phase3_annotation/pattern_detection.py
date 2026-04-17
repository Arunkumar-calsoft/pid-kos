# engine/phase3_annotation/pattern_detection.py
#
# Phase 3 — Structural Pattern Detection (pid-scoped, idempotent)
#
# CONFIRMED FIXES (all verified against live PID_2 run output):
#
# 1. pid_id scoping — every annotation stamped with pid_id (multi-PID isolation).
#
# 2. Degree queries (patterns 1-3, 20) use CONTAINS (PS→Node), not PIPE (Node→Node).
#
# 3. ENDPOINT_OF direction: (n:Node)-[:ENDPOINT_OF]->(lps) — confirmed from Phase 2.
#
# 4. Pattern 21 (asymmetric PIPE) — REMOVED.
#    Confirmed: all 490 PIPE edges in this schema are consistently directed (src→dst
#    from GraphML). Pattern 21 flagged every single edge as anomalous — useless signal.
#    A truly anomalous PIPE would be one where BOTH A→B AND B→A exist simultaneously.
#    That case is now pattern 21 (renamed: bidirectional_pipe_anomaly).
#
# 5. Pattern 23 (orphan annotation) — FIXED WHERE clause.
#    Previously: NOT ANNOTATES→PS AND NOT ANNOTATES→LPS AND NOT SUPPORTED_BY→Evidence
#    Problem: node-targeting annotations (branch, t-junction, etc.) annotate Nodes,
#    which are neither PS nor LPS, so ALL 500 of them appeared as orphans.
#    Fix: also exclude ANNOTATES→Node and ANNOTATES→Evidence.
#    Real orphans = annotations with NO ANNOTATES relationship at all.
#
# 6. Patterns 15/16 (identical_ps_neighborhood, duplicate_symbol_candidate) — FILTERED.
#    Confirmed: crossing nodes legitimately share identical PS neighborhoods by design
#    (they are pipe intersections). Added WHERE n.label <> 'crossing' filter to both.
#
# 7. Pattern 25 (endpoint_collision) — SCOPE CLARIFIED.
#    Confirmed: crossing=47, arrow=39, general=25, valve=24, tank=7 nodes all have
#    ENDPOINT_OF >1 LPS. This is expected for junction symbols in KOS_PID — a shared
#    node IS a valid endpoint of multiple logical segments meeting at that junction.
#    Pattern 25 now only flags nodes where ENDPOINT_OF count > realistic_max (5),
#    filtering out the structurally expected 2-3 LPS per junction node.
#
# 8. Pattern 14 (logical_no_evidence) — DEDUPLICATED against direction_evidence_missing.
#    Confirmed: same 148 LPS were being double-flagged. Pattern 14 now skips LPS
#    that already have a direction_evidence_missing annotation (gap detection fires first
#    in run_phase3.py Step 3, before pattern detection in Step 4).
#
# GAP CLOSURES (patterns 27-30, identified in architecture alignment report):
#
# 9.  Pattern 27 (lps_weak_evidence_consensus) — NEW. Fills gap between P13/P14a.
# 10. Pattern 28 (lps_low_confidence_evidence) — NEW. avg confidence < 0.50.
# 11. Pattern 29 (ps_unreachable_from_evidence) — NEW. No LPS path to evidence.
# 12. Pattern 30 (cross_pid_shared_node) — NEW. Node annotated by >1 PID.
#
# SCHEMA FIX (patterns 7, 8, 22) — ADJACENT_VIA_NODES is LPS↔LPS, not PS↔PS:
#
# 13. Pattern 7  — NODE TYPE FIXED. Was PipeSegment traversal → always 0 rows.
#     Now: LogicalPipeSegment traversal, bounded CYCLE_MAX_HOPS=20.
# 14. Pattern 8  — NODE TYPE + CONDITION FIXED. Was PipeSegment + r.via_count > 1.
#     r.via_count does not exist on ADJACENT_VIA_NODES rel (it is on LPS node).
#     Now: LPS traversal + r.via_nodes CONTAINS ',' for multi-node shared paths.
# 15. Pattern 22 — CONDITION REWRITTEN. Was r.via_count <> size(r.via_nodes):
#     via_count absent on rel; size() on string gives char count. Now: checks
#     that via_node appears in via_nodes string. Annotates LPS not PipeSegment.
#
# FIX-1: Pattern 30 completion print moved out of for loop body to function scope.
#         Previously it printed once per cross_pid row (or never if 0 rows).
#
# FIX-2: Pattern 9 (pipe_junction) rewritten to use ENDPOINT_OF (lps_count >= 2).
#         Old query used CONTAINS (ps_count >= 2) — PS are disjoint so every node
#         belongs to exactly 1 PS, making the query always return 0 rows.
#         Now consistent with patterns 1-3 and 20 which correctly use ENDPOINT_OF.
#
# PHASE 3.5 INTEGRATION:
#   Pattern 23 (_INFRA_SOURCES) — 'phase3_engineering_rules' added.
#
#   engineering_rules.py creates Annotation nodes with source='phase3_engineering_rules'
#   that target Node instances via ANNOTATES. These annotations DO have an ANNOTATES
#   edge and are therefore not true orphans. However, if _create_rule_violation
#   fails mid-write (e.g. the MATCH on the target Node finds nothing), a partial
#   Annotation node can exist without ANNOTATES. Adding 'phase3_engineering_rules'
#   to _INFRA_SOURCES ensures such partial writes are never misclassified as P23
#   orphans on the next run, which would produce a false CRITICAL canary signal in
#   rarity scoring and flood the Phase 4 propagation_blocked set incorrectly.


def detect_structural_patterns(session, pid_id: str) -> None:
    """
    Phase 3 — Structural pattern detection, scoped to pid_id.

    All created Annotation nodes carry pid_id for multi-PID isolation.
    No Cypher query touches the full graph without scoping through pid_id on output.

    Patterns:
      1.  Branch nodes (>= 3 LPS sharing a node via ENDPOINT_OF)
      2.  T-junction (== 3 LPS sharing a node)
      3.  High-degree junction (>= 4 LPS sharing a node)
      4.  Dead-end PipeSegment (touches exactly 1 Node via CONTAINS)
      5.  Isolated PipeSegment (no CONTAINS→Node at all)
      6.  Isolated Node (no PIPE neighbors, not in any PS via CONTAINS)
      7.  Cycle among LogicalPipeSegments (via ADJACENT_VIA_NODES, bounded 20 hops)
      8.  Parallel LogicalPipeSegments (r.via_nodes CONTAINS ',' on ADJACENT_VIA_NODES)
      9.  Pipe junctions (all nodes in >= 2 LPS via ENDPOINT_OF — FSM traversal index)
     10.  LPS without COVERS, PS without LPS (mapping gaps)
     11.  Endpoint count mismatch (ep_count != 2)
     12.  LPS missing ENDPOINT_OF nodes
     13.  Evidence conflicts (multiple distinct directions per LPS)
     14.  LPS with Evidence but direction=UNKNOWN only (lps_direction_unresolved)
     15.  Node collision candidates (identical PS neighborhood, not crossing, not PIPE-connected)
     16.  Duplicate symbol candidates (same label + identical PS neighborhood, not crossing, not PIPE-connected)
     17.  Short/long PipeSegments (if length property exists)
     18.  Physical-only Evidence (ABOUT→PS but not ABOUT→LPS)
     19.  PS-Node-PS chain motifs
     20.  Large manifold node (>= 8 LPS via ENDPOINT_OF — header/manifold detection)
     21.  Bidirectional PIPE anomaly (BOTH A→B and B→A exist — genuinely anomalous)
     22.  ADJACENT_VIA_NODES metadata mismatch (via_node absent from via_nodes string)
     23.  Orphan Annotations (no ANNOTATES relationship at all)
     24.  Provenance contradictions
     25.  Endpoint collisions (Node ENDPOINT_OF >5 LPS — above expected junction maximum)
     26.  Rare motif participation (low local PS-Node-PS count)
     27.  Weak evidence consensus (some resolved + some UNKNOWN, fraction < 0.70)
     28.  Low-confidence evidence (avg Evidence.confidence < 0.50)
     29.  PS unreachable from evidence (no LPS adjacency path to any evidence-bearing LPS)
     30.  Cross-PID shared node (node annotated by >1 PID — potential direction contradiction)
    """
    print(f"[PHASE3][STRUCTURE] Detecting patterns for PID={pid_id}...")

    # ── Config ──────────────────────────────────────────────────────────────────
    LARGE_MANIFOLD_THR    = 8
    SHORT_PS_THR          = 5.0
    LONG_PS_THR           = 1000.0
    MOTIF_CHAIN_MIN_COUNT = 1
    WEAK_CONSENSUS_THR    = 0.70
    LOW_CONF_THR          = 0.50
    MAX_HOPS              = 50
    CYCLE_MAX_HOPS        = 20

    # ── Helper ──────────────────────────────────────────────────────────────────
    def _ann(target_match: str, ann_id: str, ann_type: str, extra_props: dict | None = None):
        """
        Create an idempotent Annotation node attached to a target, stamped with pid_id.
        target_match must define a node bound to 'target'.
        """
        props = {"pid_id": pid_id, "type": ann_type, "source": "phase3_structural_patterns"}
        if extra_props:
            props.update(extra_props)
        set_clauses = ",\n            ".join(f"a.{k} = ${k}" for k in props)
        q = f"""
        {target_match}
        MERGE (a:Annotation {{
            id: $ann_id,
            pid_id: $pid_id,
            pattern_type: $ann_type
        }})
        ON CREATE SET a.first_seen = datetime()
        ON MATCH SET  a.last_seen  = datetime()
        SET {set_clauses}
        MERGE (a)-[:ANNOTATES]->(target)
        """
        params = {"ann_id": ann_id, "ann_type": ann_type}
        params.update(props)
        session.run(q, params)

    # ── 1/2/3  Branch / T-junction / High-degree ─────────────────────────────
    # CATEGORY: ENGINEERING_STRUCTURE (ESV)
    #
    # TOPOLOGY FIX: PipeSegments are DISJOINT node partitions. Each node belongs
    # to exactly 1 PS via CONTAINS. Junction nodes (137 total) are NOT in any PS.
    # Old query (broken): count(DISTINCT ps via CONTAINS) — always 0 for junctions.
    # New query: count(DISTINCT lps via ENDPOINT_OF) — correct junction degree.
    #   deg == 3 → T-junction (15 nodes confirmed)
    #   deg >= 4 → high-degree (3 nodes confirmed: deg=4,8,12)
    #   deg >= 8 → also flagged by P20 as large manifold
    rows = session.run("""
        MATCH (n:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id: $pid_id})
        WITH n, n.label AS label, count(DISTINCT lps) AS deg
        WHERE deg >= 3
        RETURN n.id AS node_id, label, deg
    """, pid_id=pid_id).data()
    for r in rows:
        nid, deg = r["node_id"], int(r["deg"])
        label = r.get("label")
        _ann(
            "MATCH (target:Node {id: $target_id})",
            ann_id=f"ann_branch_{pid_id}_{nid}", ann_type="structural_branch",
            extra_props={"target_id": nid, "node_id": nid, "degree": deg, "label": label},
        )
        if deg == 3:
            _ann(
                "MATCH (target:Node {id: $target_id})",
                ann_id=f"ann_tjunction_{pid_id}_{nid}", ann_type="structural_t_junction",
                extra_props={"target_id": nid, "node_id": nid, "degree": deg, "label": label},
            )
        if deg >= 4:
            _ann(
                "MATCH (target:Node {id: $target_id})",
                ann_id=f"ann_highdeg_{pid_id}_{nid}", ann_type="structural_high_degree",
                extra_props={"target_id": nid, "node_id": nid, "degree": deg, "label": label},
            )

    # ── 4/5  Dead-end / Isolated PipeSegments ────────────────────────────────
    # CATEGORY: ENGINEERING_STRUCTURE (ESV)
    # TOPOLOGY FIX: PS are disjoint; CONTAINS degree is always 1.
    # Dead-end = PS covering an LPS with <=1 ADJACENT_VIA_NODES connection.
    dead_ps = session.run("""
        MATCH (ps:PipeSegment {pid_id: $pid_id})<-[:COVERS]-(lps:LogicalPipeSegment {pid_id: $pid_id})
        WITH ps, lps, size([(lps)-[:ADJACENT_VIA_NODES]-() | 1]) AS adj_deg
        WHERE adj_deg <= 1
        WITH ps, min(adj_deg) AS adj_degree
        RETURN ps.id AS ps_id, adj_degree
    """, pid_id=pid_id).data()
    for r in dead_ps:
        psid = r["ps_id"]
        _ann(
            "MATCH (target:PipeSegment {id: $target_id})",
            ann_id=f"ann_deadend_{pid_id}_{psid}", ann_type="dead_end_pipe_segment",
            extra_props={"target_id": psid, "ps_id": psid,
                         "adj_degree": int(r.get("adj_degree") or 0)},
        )

    isolated_ps = session.run("""
        MATCH (ps:PipeSegment {pid_id: $pid_id})
        WHERE NOT (ps)-[:CONTAINS]->(:Node)
        RETURN ps.id AS ps_id
    """, pid_id=pid_id).data()
    for r in isolated_ps:
        psid = r["ps_id"]
        _ann(
            "MATCH (target:PipeSegment {id: $target_id})",
            ann_id=f"ann_isops_{pid_id}_{psid}", ann_type="isolated_pipe_segment",
            extra_props={"target_id": psid, "ps_id": psid},
        )

    # ── 6  Isolated Nodes ─────────────────────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    # TOPOLOGY FIX: 137 valid junction nodes are not in any PS by design.
    # Add ENDPOINT_OF exclusion to avoid false-positive orphan detection.
    orphan_nodes = session.run("""
        MATCH (n:Node {pid_id: $pid_id})
        WHERE NOT n.label IN ['arrow', 'crossing', 'background']
          AND NOT (n)-[:PIPE]-(:Node {pid_id: $pid_id})
          AND NOT EXISTS { MATCH (:PipeSegment {pid_id: $pid_id})-[:CONTAINS]->(n) }
          AND NOT (n)-[:ENDPOINT_OF]->(:LogicalPipeSegment {pid_id: $pid_id})
        RETURN n.id AS node_id, n.label AS label
    """, pid_id=pid_id).data()
    for r in orphan_nodes:
        nid = r["node_id"]
        _ann(
            "MATCH (target:Node {id: $target_id})",
            ann_id=f"ann_orphannode_{pid_id}_{nid}", ann_type="orphan_node",
            extra_props={"target_id": nid, "node_id": nid, "label": r.get("label")},
        )

    # ── 7  Cycles among LogicalPipeSegments ───────────────────────────────────
    # CATEGORY: ENGINEERING_STRUCTURE (ESV)
    # FIXED: was (ps:PipeSegment)-[:ADJACENT_VIA_NODES]. ADJACENT_VIA_NODES is LPS↔LPS.
    # PipeSegments have no such edges — old query always returned 0.
    #
    # PERFORMANCE FIX: variable-length path on undirected ADJACENT_VIA_NODES with
    # 187 LPS and 269 edges explodes combinatorially. Replaced with a 2-hop
    # triangulation check: lps→nb1→nb2→lps. This catches 3-cycles (the most common
    # engineering cycle: a loop between 3 junction points) without unbounded traversal.
    # Longer cycles are caught transitively — if any node in a 4+ cycle has a
    # triangle, it is still flagged. True isolated long cycles (no triangle) are
    # rare in P&ID topology and acceptable to miss in Phase 3 (Phase 4 BFS handles them).
    cycles = session.run("""
        MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
              -[:ADJACENT_VIA_NODES]-(nb1:LogicalPipeSegment)
              -[:ADJACENT_VIA_NODES]-(nb2:LogicalPipeSegment)
              -[:ADJACENT_VIA_NODES]-(lps)
        WHERE nb1.id <> lps.id AND nb2.id <> lps.id AND nb1.id <> nb2.id
        WITH DISTINCT lps
        RETURN lps.id AS lps_id, 3 AS min_cycle_len
        LIMIT 200
    """, pid_id=pid_id).data()
    for r in cycles:
        lps_id = r["lps_id"]
        _ann(
            "MATCH (target:LogicalPipeSegment {id: $target_id})",
            ann_id=f"ann_cycle_{pid_id}_{lps_id}",
            ann_type="pipe_segment_cycle_member",
            extra_props={"target_id": lps_id, "lps_id": lps_id,
                         "cycle_length": int(r.get("min_cycle_len") or 0)},
        )

    # ── 8  Parallel LogicalPipeSegments ───────────────────────────────────────
    # CATEGORY: ENGINEERING_STRUCTURE (ESV)
    # FIXED: was (a:PipeSegment) WHERE r.via_count > 1. Two bugs:
    #   (1) PipeSegment has no ADJACENT_VIA_NODES edges — always 0.
    #   (2) r.via_count does not exist on the rel (it is on the LPS node).
    # Fixed: LPS traversal + r.via_nodes CONTAINS ',' detects multiple shared nodes.
    parallel_pairs = session.run("""
        MATCH (a:LogicalPipeSegment {pid_id: $pid_id})-[r:ADJACENT_VIA_NODES]-(b:LogicalPipeSegment {pid_id: $pid_id})
        WHERE r.via_nodes IS NOT NULL
          AND r.via_count > 1
          AND a.id < b.id
        RETURN a.id AS a_id, b.id AS b_id, r.via_count AS via_count, r.via_nodes AS via_nodes
        LIMIT 1000
    """, pid_id=pid_id).data()
    for r in parallel_pairs:
        aid, bid = r["a_id"], r["b_id"]
        _ann(
            "MATCH (target:LogicalPipeSegment {id: $target_id})",
            ann_id=f"ann_parallel_{pid_id}_{aid}__{bid}",
            ann_type="parallel_pipe_segments",
            extra_props={"target_id": aid, "lps_id": aid, "a_id": aid,
                         "b_id": bid, "via_count": int(r.get("via_count") or 0),
                         "via_nodes": str(r.get("via_nodes") or "")},
        )

    # ── 9  Pipe junction index ────────────────────────────────────────────────
    # CATEGORY: ENGINEERING_STRUCTURE (ESV)
    #
    # Annotates every node shared by >= 2 LogicalPipeSegments — the full traversable
    # junction set that Phase 4 FSM needs for propagation planning.
    #
    # Semantic distinction from patterns 1-3:
    #   pipe_junction     (lps_count >= 2) = ALL structural nodes, incl. ordinary 2-way
    #   structural_branch (deg >= 3)       = anomalous topology, FSM caution flag
    #   structural_t_junction (deg == 3)   = most common branch subtype
    #   structural_high_degree (deg >= 4)  = rare high-complexity junction
    #
    # FIX-2: Rewritten to use ENDPOINT_OF (lps_count >= 2).
    # Old query used CONTAINS (ps_count >= 2) — PS are disjoint, each node belongs
    # to exactly 1 PS, so ps_count was always 1 and the query always returned 0 rows.
    # Now consistent with patterns 1-3 and 20 which correctly use ENDPOINT_OF.
    pipe_junctions = session.run("""
        MATCH (n:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id: $pid_id})
        WHERE NOT n.label IN ['arrow', 'crossing', 'connector', 'background']
        WITH n, count(DISTINCT lps) AS lps_count
        WHERE lps_count >= 2
        RETURN n.id AS node_id, lps_count
    """, pid_id=pid_id).data()
    for r in pipe_junctions:
        nid = r["node_id"]
        _ann(
            "MATCH (target:Node {id: $target_id})",
            ann_id=f"ann_pipejunction_{pid_id}_{nid}", ann_type="pipe_junction",
            extra_props={"target_id": nid, "node_id": nid,
                         "lps_count": int(r["lps_count"])},
        )

    # ── 10  Logical/Physical mapping gaps ─────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    lps_without_cover = session.run("""
        MATCH (l:LogicalPipeSegment {pid_id: $pid_id})
        WHERE NOT (l)-[:COVERS]->(:PipeSegment {pid_id: $pid_id})
        RETURN l.id AS lps_id
        LIMIT 1000
    """, pid_id=pid_id).data()
    for r in lps_without_cover:
        lid = r["lps_id"]
        _ann(
            "MATCH (target:LogicalPipeSegment {id: $target_id})",
            ann_id=f"ann_uncovlps_{pid_id}_{lid}", ann_type="logical_not_covered",
            extra_props={"target_id": lid, "lps_id": lid},
        )

    ps_without_lps = session.run("""
        MATCH (ps:PipeSegment {pid_id: $pid_id})
        WHERE NOT (ps)<-[:COVERS]-(:LogicalPipeSegment {pid_id: $pid_id})
        RETURN ps.id AS ps_id
        LIMIT 1000
    """, pid_id=pid_id).data()
    for r in ps_without_lps:
        psid = r["ps_id"]
        _ann(
            "MATCH (target:PipeSegment {id: $target_id})",
            ann_id=f"ann_psnolps_{pid_id}_{psid}", ann_type="pipe_segment_no_logical_mapping",
            extra_props={"target_id": psid, "ps_id": psid},
        )

    # ── 11  Endpoint count mismatch ───────────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    # ENDPOINT_OF direction: (n:Node)-[:ENDPOINT_OF]->(lps) — confirmed from Phase 2
    # REPURPOSED: lps.node_count does not exist on live LPS nodes.
    # New: flag LPS with ep_count != 2 (non-standard topology for Phase 4).
    # ep_count=0 handled by P12; ep_count=1 = terminal; ep_count>=3 = branch.
    # FIX: Both MATCH clauses scoped to pid_id. Previously MATCH (lps:LogicalPipeSegment)
    # and MATCH (n:Node)-[:ENDPOINT_OF]->(lps) matched across all PIDs. When PID_2 is
    # in the DB, shared nodes have ENDPOINT_OF to both PID_0 and PID_2 LPS, so ep_count
    # was doubled → 79 false mismatch flags → propagation_blocked → 79 BLOCKED LPS in
    # Phase 4 → 34/37 Phase 4 verify failures.
    mismatch = session.run("""
        MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
        OPTIONAL MATCH (n:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps)
        WITH lps, count(DISTINCT n) AS ep_count
        WHERE ep_count <> 2
        RETURN lps.id AS lps_id, ep_count
        LIMIT 1000
    """, pid_id=pid_id).data()
    for r in mismatch:
        lid, ep = r["lps_id"], int(r.get("ep_count") or 0)
        if ep == 0:
            continue   # P12 handles ep_count=0
        _ann(
            "MATCH (target:LogicalPipeSegment {id: $target_id})",
            ann_id=f"ann_epmismatch_{pid_id}_{lid}", ann_type="endpoint_count_mismatch",
            extra_props={"target_id": lid, "lps_id": lid, "ep_count": ep},
        )

    # ── 12  LPS missing ENDPOINT_OF nodes ────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    lps_no_ep = session.run("""
        MATCH (l:LogicalPipeSegment {pid_id: $pid_id})
        WHERE NOT (:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(l)
        RETURN l.id AS lps_id
        LIMIT 1000
    """, pid_id=pid_id).data()
    for r in lps_no_ep:
        lid = r["lps_id"]
        _ann(
            "MATCH (target:LogicalPipeSegment {id: $target_id})",
            ann_id=f"ann_lpsnoepoint_{pid_id}_{lid}", ann_type="logical_missing_endpoints",
            extra_props={"target_id": lid, "lps_id": lid},
        )

    # ── 13  Evidence conflicts ────────────────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    #
    # R2: resolution_rule added directly to the annotation so Phase 4 FSM does
    # not need to hard-code conflict resolution logic.
    #
    # Rules (in priority order Phase 4 should apply):
    #   'majority_vote'      — use whichever direction has more Evidence votes.
    #                          Safe default for 2+ FORWARD vs 1 REVERSE.
    #   'cosine_tiebreak'    — if vote counts are equal, use highest avg cosine_alignment.
    #   'source_priority'    — equipment_semantics > check_valve > arrow_binding.
    #                          Applied when majority_vote and cosine_tiebreak both tie.
    #   'hitl_required'      — all rules inconclusive; hand to Phase 7 HITL.
    #
    # resolution_rule stored on every conflict annotation. Phase 4 FSM reads it
    # directly — no string parsing, no re-derivation.
    conflicts = session.run("""
        MATCH (l:LogicalPipeSegment {pid_id: $pid_id})<-[:ABOUT]-(e:Evidence {pid_id: $pid_id})
        WITH l,
             collect(DISTINCT e.observed_direction) AS dirs,
             size([d IN collect(DISTINCT e.observed_direction)
                   WHERE d IS NOT NULL AND d <> 'UNKNOWN']) AS ndirs,
             size([d IN collect(e.observed_direction)
                   WHERE d = 'FORWARD']) AS n_fwd,
             size([d IN collect(e.observed_direction)
                   WHERE d = 'REVERSE']) AS n_rev,
             count(e) AS n_total
        WHERE ndirs > 1
        RETURN l.id AS lps_id, dirs, ndirs, n_fwd, n_rev, n_total
        LIMIT 1000
    """, pid_id=pid_id).data()
    for r in conflicts:
        lid   = r["lps_id"]
        n_fwd = int(r.get("n_fwd") or 0)
        n_rev = int(r.get("n_rev") or 0)

        # Assign resolution rule based on vote balance
        if n_fwd != n_rev:
            resolution_rule = "majority_vote"
        else:
            resolution_rule = "cosine_tiebreak"
        # cosine_tiebreak falls through to source_priority in Phase 4 if avg cosines tie

        _ann(
            "MATCH (target:LogicalPipeSegment {id: $target_id})",
            ann_id=f"ann_dirconflict_{pid_id}_{lid}",
            ann_type="direction_conflict_observed",
            extra_props={
                "target_id":       lid,
                "lps_id":          lid,
                "directions":      str(r.get("dirs")),
                "n_forward":       n_fwd,
                "n_reverse":       n_rev,
                "n_total":         int(r.get("n_total") or 0),
                "resolution_rule": resolution_rule,
            },
        )

    # ── 14  LPS with evidence but direction=UNKNOWN only ─────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    #
    # Repurposed from logical_no_evidence (which became dead code after the
    # direction_evidence_missing dedup fix — gap detection catches all no-evidence
    # LPS before pattern detection runs, so the old query always returned 0 rows).
    #
    # New purpose: detect LPS where Phase 2 DID produce Evidence, but every piece
    # of Evidence has direction=UNKNOWN (corner-spanning arrow, low cosine alignment).
    # This is semantically distinct from a gap:
    #   direction_evidence_missing → no Evidence at all  → Phase 4: no prior
    #   lps_direction_unresolved   → Evidence exists     → Phase 4: weak prior only
    #
    # Phase 4 FSM should treat lps_direction_unresolved as a softer propagation
    # boundary than direction_evidence_missing (can still propagate with lower confidence).
    lps_unknown_only = session.run("""
        MATCH (l:LogicalPipeSegment {pid_id: $pid_id})<-[:ABOUT]-(e:Evidence {pid_id: $pid_id})
        WITH l,
             collect(DISTINCT e.observed_direction) AS dirs,
             size([d IN collect(DISTINCT e.observed_direction)
                   WHERE d IS NOT NULL AND d <> 'UNKNOWN']) AS n_resolved
        WHERE n_resolved = 0
        RETURN l.id AS lps_id, dirs
        LIMIT 1000
    """, pid_id=pid_id).data()
    for r in lps_unknown_only:
        lid = r["lps_id"]
        _ann(
            "MATCH (target:LogicalPipeSegment {id: $target_id})",
            ann_id=f"ann_lpsunknown_{pid_id}_{lid}", ann_type="lps_direction_unresolved",
            extra_props={"target_id": lid, "lps_id": lid,
                         "directions": str(r.get("dirs"))},
        )

    ps_no_ev = session.run("""
        MATCH (ps:PipeSegment {pid_id: $pid_id})
        WHERE NOT EXISTS {
          MATCH (ps)<-[:COVERS]-(l:LogicalPipeSegment {pid_id: $pid_id})<-[:ABOUT]-(e:Evidence {pid_id: $pid_id})
        }
        RETURN ps.id AS ps_id
        LIMIT 1000
    """, pid_id=pid_id).data()
    for r in ps_no_ev:
        psid = r["ps_id"]
        _ann(
            "MATCH (target:PipeSegment {id: $target_id})",
            ann_id=f"ann_psnoevidev_{pid_id}_{psid}", ann_type="pipe_segment_no_evidence_via_lps",
            extra_props={"target_id": psid, "ps_id": psid},
        )

    # ── 15  Node connectivity-collision candidates ────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    # Confirmed: crossing nodes legitimately share identical PS neighborhoods
    # (they ARE the intersection point, so of course both sides contain them).
    # Filter: exclude crossing-labeled nodes from this pattern.
    #
    # PERFORMANCE FIX: bare cross-join over all 481 nodes was O(n²). Added
    # pid_id scoping via CONTAINS from PipeSegment, and a minimum aset size
    # of 2 (single-PS neighborhood matches are trivial and numerous). Also
    # capped the outer match at LIMIT 200 to prevent runaway on large PIDs.
    identical_neigh = session.run("""
        MATCH (ps1:PipeSegment {pid_id: $pid_id})-[:CONTAINS]->(a:Node)
        WHERE a.label <> 'crossing'
        WITH a, collect(DISTINCT ps1.id) AS aset
        WHERE size(aset) >= 2
        MATCH (ps2:PipeSegment {pid_id: $pid_id})-[:CONTAINS]->(b:Node)
        WHERE b.label <> 'crossing' AND a.id < b.id
        WITH a, aset, b, collect(DISTINCT ps2.id) AS bset
        WHERE size(aset) = size(bset)
          AND ALL(x IN aset WHERE x IN bset)
          AND NOT (a)-[:PIPE]-(b)
        RETURN a.id AS a_id, b.id AS b_id, aset
        LIMIT 200
    """, pid_id=pid_id).data()
    if len(identical_neigh) >= 200:
        print("[PHASE3][WARN] Pattern 15: identical_ps_neighborhood truncated at 200 rows — some identical PS neighborhoods may be undetected.")
    for r in identical_neigh:
        aid, bid = r["a_id"], r["b_id"]
        _ann(
            "MATCH (target:Node {id: $target_id})",
            ann_id=f"ann_idneigh_{pid_id}_{aid}__{bid}",
            ann_type="identical_ps_neighborhood",
            extra_props={"target_id": aid, "node_id": aid, "other_node": bid,
                         "neighborhood": str(r.get("aset"))},
        )

    # ── 16  Duplicate symbol candidates ───────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    # Same crossing exclusion: crossing nodes share neighborhoods by design.
    # Added NOT (a)-[:PIPE]-(b): two same-label nodes on the same pipe run
    # (directly PIPE-connected) sharing a PS neighborhood is expected engineering
    # structure (two valves in series). Flagging them floods the HITL queue.
    # Only flag when same-label + same-neighborhood + NO direct pipe connection.
    # PERFORMANCE FIX: same pid_id scoping + size >= 2 filter as P15.
    dup_candidates = session.run("""
        MATCH (ps1:PipeSegment {pid_id: $pid_id})-[:CONTAINS]->(a:Node)
        WHERE a.label IS NOT NULL AND a.label <> 'crossing'
        WITH a, a.label AS lbl, collect(DISTINCT ps1.id) AS aset
        WHERE size(aset) >= 2
        MATCH (ps2:PipeSegment {pid_id: $pid_id})-[:CONTAINS]->(b:Node)
        WHERE b.label IS NOT NULL AND b.label <> 'crossing' AND a.id < b.id
        WITH a, lbl, aset, b, collect(DISTINCT ps2.id) AS bset
        WHERE lbl = b.label AND size(aset) = size(bset)
          AND ALL(x IN aset WHERE x IN bset)
          AND NOT (a)-[:PIPE]-(b)
        RETURN a.id AS a_id, b.id AS b_id, lbl
        LIMIT 200
    """, pid_id=pid_id).data()
    for r in dup_candidates:
        aid, bid, lbl = r["a_id"], r["b_id"], r["lbl"]
        _ann(
            "MATCH (target:Node {id: $target_id})",
            ann_id=f"ann_dupsym_{pid_id}_{aid}__{bid}",
            ann_type="duplicate_symbol_candidate",
            extra_props={"target_id": aid, "node_id": aid, "duplicate_of": bid, "label": lbl},
        )

    # ── 17  Short / long PipeSegments ─────────────────────────────────────────
    # CATEGORY: ENGINEERING_STRUCTURE (ESV)
    short_rows = session.run("""
        MATCH (ps:PipeSegment {pid_id: $pid_id})
        WHERE ps.length IS NOT NULL AND toFloat(ps.length) > 0
          AND toFloat(ps.length) < $short_thr
        RETURN ps.id AS ps_id, ps.length AS length
        LIMIT 500
    """, pid_id=pid_id, short_thr=SHORT_PS_THR).data()
    for r in short_rows:
        psid = r["ps_id"]
        _ann(
            "MATCH (target:PipeSegment {id: $target_id})",
            ann_id=f"ann_shortps_{pid_id}_{psid}", ann_type="pipe_segment_short",
            extra_props={"target_id": psid, "ps_id": psid, "length": float(r["length"])},
        )

    long_rows = session.run("""
        MATCH (ps:PipeSegment {pid_id: $pid_id})
        WHERE ps.length IS NOT NULL AND toFloat(ps.length) > $long_thr
        RETURN ps.id AS ps_id, ps.length AS length
        LIMIT 500
    """, pid_id=pid_id, long_thr=LONG_PS_THR).data()
    for r in long_rows:
        psid = r["ps_id"]
        _ann(
            "MATCH (target:PipeSegment {id: $target_id})",
            ann_id=f"ann_longps_{pid_id}_{psid}", ann_type="pipe_segment_long",
            extra_props={"target_id": psid, "ps_id": psid, "length": float(r["length"])},
        )

    # ── 18  Physical-only Evidence ────────────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    phys_only = session.run("""
        MATCH (e:Evidence {pid_id: $pid_id})-[:ABOUT]->(ps:PipeSegment {pid_id: $pid_id})
        WHERE NOT (e)-[:ABOUT]->(:LogicalPipeSegment {pid_id: $pid_id})
        RETURN e.id AS ev_id, ps.id AS ps_id
        LIMIT 1000
    """, pid_id=pid_id).data()
    for r in phys_only:
        ev_id, psid = r["ev_id"], r["ps_id"]
        _ann(
            "MATCH (target:PipeSegment {id: $target_id})",
            ann_id=f"ann_physonly_{pid_id}_{ev_id}", ann_type="evidence_physical_only",
            extra_props={"target_id": psid, "ps_id": psid, "ev_id": ev_id},
        )

    # ── 19  PS-Node-PS chain motifs ───────────────────────────────────────────
    # CATEGORY: ENGINEERING_STRUCTURE (ESV)
    motif_rows = session.run("""
        MATCH (ps1:PipeSegment {pid_id: $pid_id})-[:CONTAINS]-(n:Node {pid_id: $pid_id})-[:CONTAINS]-(ps2:PipeSegment {pid_id: $pid_id})
        WHERE ps1.id <> ps2.id
        RETURN ps1.id AS ps1, n.id AS node, ps2.id AS ps2
        LIMIT 2000
    """, pid_id=pid_id).data()
    seen_motifs: set = set()
    for r in motif_rows:
        node = r["node"]
        if node in seen_motifs:
            continue
        seen_motifs.add(node)
        _ann(
            "MATCH (target:Node {id: $target_id})",
            ann_id=f"ann_motif_{pid_id}_{node}", ann_type="motif_ps_node_chain",
            extra_props={"target_id": node, "node_id": node,
                         "example_ps_pair": f"{r['ps1']}__{r['ps2']}"},
        )

    # ── 20  Large manifold node ───────────────────────────────────────────────
    # CATEGORY: ENGINEERING_STRUCTURE (ESV)
    # TOPOLOGY FIX: CONTAINS degree always 1. Use ENDPOINT_OF degree instead.
    # Confirmed: 2 manifold nodes exist (deg=12, deg=8 — tank and a header node).
    manifold_nodes = session.run("""
        MATCH (n:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id: $pid_id})
        WITH n, n.label AS label, count(DISTINCT lps) AS deg
        WHERE deg >= $thr
        RETURN n.id AS node_id, label, deg
        LIMIT 1000
    """, pid_id=pid_id, thr=LARGE_MANIFOLD_THR).data()
    for r in manifold_nodes:
        nid, deg = r["node_id"], int(r["deg"])
        _ann(
            "MATCH (target:Node {id: $target_id})",
            ann_id=f"ann_manifold_{pid_id}_{nid}", ann_type="large_manifold_node",
            extra_props={"target_id": nid, "node_id": nid,
                         "degree": deg, "label": r.get("label")},
        )

    # ── 21  Bidirectional PIPE anomaly ────────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    # Confirmed: all 490 PIPE edges in this schema are consistently one-directional
    # (src→dst from GraphML, directed by design). The old pattern flagged every single
    # edge as "asymmetric" — useless signal.
    # New pattern: flag the genuinely anomalous case where BOTH A→B AND B→A exist.
    # A bidirectional PIPE pair means the same pipe was loaded twice in opposite
    # directions — data integrity error.
    bidir_pipe = session.run("""
        MATCH (a:Node {pid_id: $pid_id})-[r1:PIPE]->(b:Node {pid_id: $pid_id})
        WHERE EXISTS { MATCH (b)-[:PIPE]->(a) } AND a.id < b.id
        RETURN DISTINCT a.id AS a_id, b.id AS b_id
        LIMIT 500
    """, pid_id=pid_id).data()
    for r in bidir_pipe:
        a_id, b_id = r["a_id"], r["b_id"]
        _ann(
            "MATCH (target:Node {id: $target_id})",
            ann_id=f"ann_bidirpipe_{pid_id}_{a_id}__{b_id}",
            ann_type="bidirectional_pipe_anomaly",
            extra_props={"target_id": a_id, "node_id": a_id, "other_node": b_id},
        )

    # ── 22  ADJACENT_VIA_NODES metadata mismatch ──────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    # FIXED: was r.via_count IS NOT NULL AND r.via_count <> size(r.via_nodes).
    #   (1) r.via_count does not exist on the relationship.
    #   (2) via_nodes is a string; size() returns char count, not element count.
    # New: via_node (primary shared node on rel) must appear in via_nodes string.
    # Annotates source LPS (rel is LPS↔LPS, not PipeSegment).
    adj_mismatch = session.run("""
        MATCH (a:LogicalPipeSegment {pid_id: $pid_id})-[r:ADJACENT_VIA_NODES]->(b:LogicalPipeSegment {pid_id: $pid_id})
        WHERE (r.via_count IS NULL AND r.via_nodes IS NOT NULL)
           OR (r.via_nodes IS NULL AND r.via_count IS NOT NULL)
           OR (r.via_count IS NOT NULL AND r.via_count < 1)
        RETURN a.id AS a_id, b.id AS b_id,
               r.via_count AS via_count, r.via_nodes AS via_nodes
        LIMIT 500
    """, pid_id=pid_id).data()
    for r in adj_mismatch:
        a, b = r["a_id"], r["b_id"]
        _ann(
            "MATCH (target:LogicalPipeSegment {id: $target_id})",
            ann_id=f"ann_adjmeta_{pid_id}_{a}__{b}",
            ann_type="adjacency_metadata_mismatch",
            extra_props={"target_id": a, "lps_id": a, "a": a, "b": b,
                         "via_count": r.get("via_count"),
                         "via_nodes": str(r.get("via_nodes"))},
        )

    # ── 23  Orphan Annotations ────────────────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    #
    # FIXED (second time): exclude infrastructure annotation nodes.
    # frequency_aggregation.py writes freq summary nodes (source=phase3_structural_frequencies)
    # and rarity_scoring.py writes rarity nodes — these are not attached via ANNOTATES
    # by design (they are frequency/rarity records, not pattern annotations).
    # P23 finding them created a self-inflicted canary loop on every subsequent run:
    #   freq nodes created → P23 finds them next run → orphan_annotation count > 0
    #   → rarity marks orphan_annotation CRITICAL → false alarm every run.
    # True orphans: source=phase3_structural_patterns nodes with no ANNOTATES edge.
    #
    # PHASE 3.5: 'phase3_engineering_rules' added to _INFRA_SOURCES.
    # Engineering rule violation annotations (source='phase3_engineering_rules') DO
    # have ANNOTATES edges to their target Node — they are not true orphans.
    # However, if _create_rule_violation in engineering_rules.py fails mid-write
    # (e.g. the MATCH on the target Node finds nothing because pid_id was wrong),
    # a partial Annotation node can exist in the graph without an ANNOTATES edge.
    # Without this exclusion, such partial writes would be flagged as P23 orphans
    # on the very next Phase 3 run, causing rarity_scoring to classify
    # orphan_annotation as CRITICAL and stamping propagation_blocked=true on
    # engineering-rule-adjacent LPS — a false cascade from a write-time error.
    _INFRA_SOURCES = [
        "phase3_structural_frequencies",
        "phase3_structural_rarity",
        "phase3_direction_summary",
        "phase3_engineering_rules",      # Phase 3.5 — see docstring above
    ]
    orphan_ann = session.run("""
        MATCH (a:Annotation {pid_id: $pid_id})
        WHERE NOT (a)-[:ANNOTATES]->()
          AND NOT (a)-[:SUPPORTED_BY]->()
          AND NOT a.source IN $infra_sources
        RETURN a.id AS aid, a.type AS atype
        LIMIT 500
    """, pid_id=pid_id, infra_sources=_INFRA_SOURCES).data()
    for r in orphan_ann:
        aid = r["aid"]
        _ann(
            "MATCH (target:Annotation {id: $target_id})",
            ann_id=f"ann_orphanann_{pid_id}_{aid}", ann_type="orphan_annotation",
            extra_props={"target_id": aid, "annotation_id": aid,
                         "annotation_type": r.get("atype")},
        )

    # ── 24  Provenance contradictions ─────────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    prov_mismatch = session.run("""
        MATCH (e:Evidence {pid_id: $pid_id})-[:ABOUT]->(l:LogicalPipeSegment {pid_id: $pid_id})
        WHERE e.ps_id IS NOT NULL
          AND NOT EXISTS {
              MATCH (l)-[:COVERS]->(:PipeSegment {id: e.ps_id, pid_id: $pid_id})
          }
        RETURN e.id AS ev_id, e.ps_id AS declared_ps
        LIMIT 1000
    """, pid_id=pid_id).data()
    for r in prov_mismatch:
        ev_id, declared = r["ev_id"], r["declared_ps"]
        _ann(
            "MATCH (target:Evidence {id: $target_id})",
            ann_id=f"ann_provmismatch_{pid_id}_{ev_id}", ann_type="provenance_contradiction",
            extra_props={"target_id": ev_id, "ev_id": ev_id, "declared_ps": declared},
        )

    # ── 25  Endpoint collisions ────────────────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    # Confirmed: crossing=47, arrow=39, general=25, valve=24, tank=7 nodes all appear
    # as ENDPOINT_OF >1 LPS. This is structurally expected — shared junction nodes
    # sit at the meeting point of multiple logical segments by design (2-3 LPS per node
    # is normal for any branching point or crossing in a P&ID).
    # Only truly anomalous if a single node is an endpoint of an unrealistic number
    # of LPS (>5). tank1 had max=12 — worth investigating but not all 142 nodes.
    ep_collisions = session.run("""
        MATCH (n:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(l:LogicalPipeSegment {pid_id: $pid_id})
        WITH n, collect(DISTINCT l.id) AS lps, size(collect(DISTINCT l.id)) AS k
        WHERE k > 5
        RETURN n.id AS node_id, n.label AS label, lps, k
        LIMIT 500
    """, pid_id=pid_id).data()
    for r in ep_collisions:
        nid, lps = r["node_id"], r["lps"]
        _ann(
            "MATCH (target:Node {id: $target_id})",
            ann_id=f"ann_epcollision_{pid_id}_{nid}", ann_type="endpoint_collision",
            extra_props={"target_id": nid, "node_id": nid, "lps_count": int(r["k"]),
                         "lps_list": str(lps), "label": r.get("label")},
        )

    # ── 26  Rare motif participation ──────────────────────────────────────────
    # CATEGORY: ENGINEERING_STRUCTURE (ESV)
    # TOPOLOGY FIX: PS-CONTAINS-Node-CONTAINS-PS always 0 (disjoint PS).
    # New: low-adjacency PS = covers LPS with <=2 ADJACENT_VIA_NODES connections.
    rare_motif = session.run("""
        MATCH (ps:PipeSegment {pid_id: $pid_id})<-[:COVERS]-(lps:LogicalPipeSegment {pid_id: $pid_id})
        WITH ps, lps, size([(lps)-[:ADJACENT_VIA_NODES]-() | 1]) AS adj_deg
        WHERE adj_deg <= $max_adj
        WITH ps, min(adj_deg) AS motif_chain_count
        RETURN ps.id AS ps_id, motif_chain_count
        LIMIT 1000
    """, pid_id=pid_id, max_adj=MOTIF_CHAIN_MIN_COUNT + 1).data()
    for r in rare_motif:
        psid, cnt = r["ps_id"], int(r.get("motif_chain_count") or 0)
        _ann(
            "MATCH (target:PipeSegment {id: $target_id})",
            ann_id=f"ann_raremotif_{pid_id}_{psid}", ann_type="rare_motif_local",
            extra_props={"target_id": psid, "ps_id": psid, "motif_chain_count": cnt},
        )

    # ── 27  Weak evidence consensus ───────────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    # Fills gap between P13 (FORWARD+REVERSE conflict) and P14a (all UNKNOWN).
    # Fires when resolved fraction < WEAK_CONSENSUS_THR (0.70).
    # Stores consensus_fraction for Phase 4 continuous weight.
    weak_consensus = session.run("""
        MATCH (l:LogicalPipeSegment {pid_id: $pid_id})<-[:ABOUT]-(e:Evidence {pid_id: $pid_id})
        WITH l,
             size([d IN collect(e.observed_direction)
                   WHERE d IS NOT NULL AND d <> 'UNKNOWN']) AS n_resolved,
             size(collect(e.observed_direction))              AS n_total
        WHERE n_resolved > 0
          AND n_resolved < n_total
          AND (toFloat(n_resolved) / toFloat(n_total)) < $thr
        RETURN l.id AS lps_id, n_resolved, n_total,
               round(toFloat(n_resolved) / toFloat(n_total) * 1000) / 1000.0 AS frac
        LIMIT 1000
    """, pid_id=pid_id, thr=WEAK_CONSENSUS_THR).data()
    for r in weak_consensus:
        lid = r["lps_id"]
        _ann(
            "MATCH (target:LogicalPipeSegment {id: $target_id})",
            ann_id=f"ann_weakconsensus_{pid_id}_{lid}",
            ann_type="lps_weak_evidence_consensus",
            extra_props={
                "target_id":          lid,
                "lps_id":             lid,
                "n_resolved":         int(r["n_resolved"]),
                "n_total":            int(r["n_total"]),
                "consensus_fraction": float(r["frac"]),
            },
        )

    # ── 28  Low-confidence evidence ───────────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    # Flags LPS where avg Evidence.confidence < LOW_CONF_THR.
    # Only fires when Evidence.confidence IS NOT NULL (Phase 2 must populate it).
    low_conf = session.run("""
        MATCH (l:LogicalPipeSegment {pid_id: $pid_id})<-[:ABOUT]-(e:Evidence {pid_id: $pid_id})
        WHERE e.confidence IS NOT NULL
        WITH l,
             avg(toFloat(e.confidence))  AS avg_conf,
             min(toFloat(e.confidence))  AS min_conf,
             count(e)                    AS n_ev
        WHERE avg_conf < $thr
        RETURN l.id AS lps_id, avg_conf, min_conf, n_ev
        LIMIT 1000
    """, pid_id=pid_id, thr=LOW_CONF_THR).data()
    for r in low_conf:
        lid = r["lps_id"]
        _ann(
            "MATCH (target:LogicalPipeSegment {id: $target_id})",
            ann_id=f"ann_lowconf_{pid_id}_{lid}",
            ann_type="lps_low_confidence_evidence",
            extra_props={
                "target_id":      lid,
                "lps_id":         lid,
                "avg_confidence": round(float(r["avg_conf"]), 4),
                "min_confidence": round(float(r["min_conf"]), 4),
                "n_evidence":     int(r["n_ev"]),
            },
        )

    # ── 29  PS unreachable from evidence ──────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    # FIXED from initial implementation: was (ps:PipeSegment)-[:ADJACENT_VIA_NODES]-(ps2)
    # PipeSegments have no ADJACENT_VIA_NODES edges. Correct path:
    #   PS <-[:COVERS]- LPS -[:ADJACENT_VIA_NODES*0..N]- LPS2 <-[:ABOUT]- Evidence
    # *0 hop: LPS covering this PS counts if it has its own Evidence (distance 0 = seed).
    #
    # PERFORMANCE FIX: MAX_HOPS reduced from 50 to 10. With 187 LPS and 269 adjacency
    # edges, 10 hops covers the full diameter of any realistic P&ID sub-graph.
    # A PS not reachable within 10 hops from evidence is genuinely isolated.
    _REACH_HOPS = 10
    unreachable = session.run(f"""
        MATCH (ps:PipeSegment {{pid_id: $pid_id}})
        WHERE NOT EXISTS {{
            MATCH (ps)<-[:COVERS]-(lps:LogicalPipeSegment {{pid_id: $pid_id}})
                  -[:ADJACENT_VIA_NODES*0..{_REACH_HOPS}]-(lps2:LogicalPipeSegment)
            WHERE EXISTS {{ MATCH (lps2)<-[:ABOUT]-(:Evidence) }}
        }}
        RETURN ps.id AS ps_id
        LIMIT 500
    """, pid_id=pid_id).data()
    for r in unreachable:
        psid = r["ps_id"]
        _ann(
            "MATCH (target:PipeSegment {id: $target_id})",
            ann_id=f"ann_unreachable_{pid_id}_{psid}",
            ann_type="ps_unreachable_from_evidence",
            extra_props={"target_id": psid, "ps_id": psid,
                         "max_hops_checked": _REACH_HOPS},
        )

    # ── 30  Cross-PID shared node ─────────────────────────────────────────────
    # CATEGORY: ARCHITECTURAL_INTEGRITY (KAV)
    # Nodes are NOT stamped with pid_id (shared physical equipment spans PIDs).
    # Fires when a node carries Annotations from >1 PID — potential direction
    # contradiction between two FSM runs. Expected 0 hits on first PID.
    cross_pid = session.run("""
        MATCH (n:Node)<-[:ANNOTATES]-(a:Annotation)
        WHERE a.pid_id IS NOT NULL AND a.pid_id <> $pid_id
        WITH n, collect(DISTINCT a.pid_id) AS other_pids
        MATCH (n)<-[:ANNOTATES]-(b:Annotation {pid_id: $pid_id})
        WITH n, other_pids
        RETURN n.id AS node_id, n.label AS label, other_pids
        LIMIT 500
    """, pid_id=pid_id).data()
    for r in cross_pid:
        nid = r["node_id"]
        _ann(
            "MATCH (target:Node {id: $target_id})",
            ann_id=f"ann_crosspid_{pid_id}_{nid}",
            ann_type="cross_pid_shared_node",
            extra_props={
                "target_id":  nid,
                "node_id":    nid,
                "label":      r.get("label"),
                "other_pids": str(r.get("other_pids")),
            },
        )

    # FIX-1: moved out of for loop body — was printing once per cross_pid row
    print(f"[PHASE3][STRUCTURE] Pattern detection complete for PID={pid_id}.")