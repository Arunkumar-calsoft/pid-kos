# tests/verify_phase4.py
#
# Phase 4 — FSM Output Verification (READ-ONLY)
#
# Usage:
#   python tests/verify_phase4.py --pid PID_2
#
# EXIT CODE: 0 = all checks pass (Phase 5 safe to run)
#            1 = one or more checks failed
#
# COVERAGE: 37 checks across 9 sections
#
#   1. LPS flow_state coverage   — all LPS have state, valid values, arithmetic
#   2. SEEDED / SEEDED_UNKNOWN   — Evidence present, direction + source correct
#   3. PROPAGATED                — direction, confidence, reachability, decay
#   4. BLOCKED / HITL_PENDING    — source, annotation cross-check
#   5. UNKNOWN                   — no evidence, isolated, zero confidence
#   6. flow_confidence range     — (0,1] on active states, no nulls
#   7. Phase 3 contract stamps   — phase4_blocked/phase4_hint integrity
#   8. Equipment node assignment — valid states, parent consistency, unassigned
#   9. Cross-PID isolation       — no contamination from other PIDs
#  10. PID status + trace file   — PHASE4_COMPLETE, trace exists, correct count

import argparse
import json
import logging
import os
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader
from engine.phase4_fsm.flow_assignment import EQUIPMENT_NODE_LABELS

logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")

# ── Valid value sets ───────────────────────────────────────────────────────────

VALID_FLOW_STATES = {
    "SEEDED", "SEEDED_UNKNOWN", "PROPAGATED",
    "BLOCKED", "UNKNOWN", "HITL_PENDING",
}
VALID_DIRECTIONS = {"FORWARD", "REVERSE", "UNKNOWN"}
VALID_SOURCES    = {
    "evidence", "propagated", "propagation_blocked",
    "hitl_required", "none",
}


# ── Logging helpers ────────────────────────────────────────────────────────────

_failures: list = []

def info(msg):  print(f"  [INFO] {msg}")
def warn(msg):  print(f"  [WARN] {msg}")

def check(passed: bool, name: str, detail: str = "") -> bool:
    sym = "✅" if passed else "❌"
    suffix = f"  — {detail}" if detail else ""
    print(f"  {sym} {name}{suffix}")
    if not passed:
        _failures.append(name)
    return passed

def header(title: str):
    print(f"\n{'─'*68}")
    print(f"  {title}")
    print(f"{'─'*68}")


# ── Query helpers ──────────────────────────────────────────────────────────────

def scalar(session, q: str, params: dict | None = None, key: str = "c") -> int:
    r = session.run(q, **(params or {})).single()
    return int(r[key]) if r and r.get(key) is not None else 0

def rows(session, q: str, params: dict | None = None) -> list:
    return session.run(q, **(params or {})).data()

def P(pid_id: str) -> dict:
    return {"pid_id": pid_id}


# ── 1. LPS flow_state coverage ─────────────────────────────────────────────────

def check_coverage(session, pid_id: str) -> dict:
    lps_total = scalar(session,
        "MATCH (lps:LogicalPipeSegment {pid_id:$pid_id}) RETURN count(lps) AS c",
        P(pid_id))
    info(f"LPS total: {lps_total}")

    # 1a — no null flow_state
    null_state = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.flow_state IS NULL
        RETURN count(lps) AS c
    """, P(pid_id))
    check(null_state == 0, "Coverage: all LPS have flow_state set",
          f"{null_state} missing" if null_state else "")

    # 1b — valid state values
    invalid_state = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE NOT lps.flow_state IN
              ['SEEDED','SEEDED_UNKNOWN','PROPAGATED','BLOCKED','UNKNOWN','HITL_PENDING']
        RETURN count(lps) AS c
    """, P(pid_id))
    check(invalid_state == 0, "Coverage: all flow_state values in valid set",
          f"{invalid_state} invalid" if invalid_state else "")

    # 1c — state arithmetic
    state_counts = rows(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        RETURN lps.flow_state AS state, count(lps) AS n
        ORDER BY n DESC
    """, P(pid_id))
    count_map = {r["state"]: int(r["n"]) for r in state_counts}
    total_counted = sum(count_map.values())
    check(total_counted == lps_total,
          "Coverage: state counts sum to lps_total",
          f"sum={total_counted}, lps_total={lps_total}")
    for state, n in sorted(count_map.items(), key=lambda x: -x[1]):
        pct = 100.0 * n / max(lps_total, 1)
        info(f"  {state:<22} n={n:<5} ({pct:.1f}%)")

    # 1d — SEEDED+SEEDED_UNKNOWN matches Phase 3 evidence_lps
    seeded_total = count_map.get("SEEDED", 0) + count_map.get("SEEDED_UNKNOWN", 0)
    evidence_lps = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE (lps)<-[:ABOUT]-(:Evidence {pid_id:$pid_id})
        RETURN count(lps) AS c
    """, P(pid_id))
    check(seeded_total == evidence_lps,
          "Coverage: SEEDED+SEEDED_UNKNOWN == Phase 3 evidence_lps",
          f"seeded={seeded_total}, evidence_lps={evidence_lps}")

    return {
        "lps_total":    lps_total,
        "count_map":    count_map,
        "evidence_lps": evidence_lps,
    }


# ── 2. SEEDED / SEEDED_UNKNOWN ─────────────────────────────────────────────────

def check_seeded(session, pid_id: str) -> dict:
    # 2a — all SEEDED/SEEDED_UNKNOWN have Evidence
    no_ev = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.flow_state IN ['SEEDED','SEEDED_UNKNOWN']
          AND NOT (lps)<-[:ABOUT]-(:Evidence {pid_id:$pid_id})
        RETURN count(lps) AS c
    """, P(pid_id))
    check(no_ev == 0, "Seeded: all SEEDED/SEEDED_UNKNOWN have Evidence",
          f"{no_ev} missing Evidence" if no_ev else "")

    # 2b — SEEDED have FORWARD or REVERSE
    bad_dir = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'SEEDED'})
        WHERE NOT lps.flow_direction IN ['FORWARD','REVERSE']
        RETURN count(lps) AS c
    """, P(pid_id))
    check(bad_dir == 0, "Seeded: SEEDED have flow_direction FORWARD or REVERSE",
          f"{bad_dir} wrong" if bad_dir else "")

    # 2c — SEEDED_UNKNOWN have direction = UNKNOWN
    bad_unknown_dir = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'SEEDED_UNKNOWN'})
        WHERE lps.flow_direction <> 'UNKNOWN'
        RETURN count(lps) AS c
    """, P(pid_id))
    check(bad_unknown_dir == 0, "Seeded: SEEDED_UNKNOWN have flow_direction='UNKNOWN'",
          f"{bad_unknown_dir} wrong" if bad_unknown_dir else "")

    # 2d — SEEDED have confidence > 0
    zero_conf = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'SEEDED'})
        WHERE coalesce(toFloat(lps.flow_confidence), 0.0) <= 0.0
        RETURN count(lps) AS c
    """, P(pid_id))
    check(zero_conf == 0, "Seeded: SEEDED have flow_confidence > 0",
          f"{zero_conf} with zero/null" if zero_conf else "")

    # 2e — SEEDED/SEEDED_UNKNOWN have flow_source = 'evidence'
    bad_src = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.flow_state IN ['SEEDED','SEEDED_UNKNOWN']
          AND lps.flow_source <> 'evidence'
        RETURN count(lps) AS c
    """, P(pid_id))
    check(bad_src == 0, "Seeded: flow_source = 'evidence'",
          f"{bad_src} wrong" if bad_src else "")

    return {"no_ev": no_ev, "bad_dir": bad_dir}


# ── 3. PROPAGATED ──────────────────────────────────────────────────────────────

def check_propagated(session, pid_id: str, count_map: dict) -> dict:
    prop_count = count_map.get("PROPAGATED", 0)
    if prop_count == 0:
        info("No PROPAGATED LPS — skipping section 3")
        return {}

    # 3a — PROPAGATED have FORWARD or REVERSE
    bad_dir = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'PROPAGATED'})
        WHERE NOT lps.flow_direction IN ['FORWARD','REVERSE']
        RETURN count(lps) AS c
    """, P(pid_id))
    check(bad_dir == 0, "Propagated: flow_direction FORWARD or REVERSE",
          f"{bad_dir} wrong" if bad_dir else "")

    # 3b — PROPAGATED have confidence > 0
    zero_conf = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'PROPAGATED'})
        WHERE coalesce(toFloat(lps.flow_confidence), 0.0) <= 0.0
        RETURN count(lps) AS c
    """, P(pid_id))
    check(zero_conf == 0, "Propagated: flow_confidence > 0",
          f"{zero_conf} zero/null" if zero_conf else "")

    # 3c — flow_source = 'propagated'
    bad_src = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'PROPAGATED'})
        WHERE lps.flow_source <> 'propagated'
        RETURN count(lps) AS c
    """, P(pid_id))
    check(bad_src == 0, "Propagated: flow_source = 'propagated'",
          f"{bad_src} wrong" if bad_src else "")

    # 3d — each PROPAGATED has at least one SEEDED/PROPAGATED neighbour
    unreachable = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'PROPAGATED'})
        WHERE NOT EXISTS {
            MATCH (lps)-[:ADJACENT_VIA_NODES]-(nb:LogicalPipeSegment {pid_id:$pid_id})
            WHERE nb.flow_state IN ['SEEDED','PROPAGATED','SEEDED_UNKNOWN']
        }
        RETURN count(lps) AS c
    """, P(pid_id))
    check(unreachable == 0, "Propagated: each LPS has a SEEDED/PROPAGATED neighbour",
          f"{unreachable} isolated" if unreachable else "")

    # 3e — confidence <= 1.0
    over_one = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'PROPAGATED'})
        WHERE toFloat(coalesce(lps.flow_confidence, 0.0)) > 1.0
        RETURN count(lps) AS c
    """, P(pid_id))
    check(over_one == 0, "Propagated: flow_confidence <= 1.0",
          f"{over_one} > 1.0" if over_one else "")

    # 3f — avg PROPAGATED confidence < avg SEEDED confidence (BFS decayed)
    conf_stats = rows(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.flow_state IN ['SEEDED','PROPAGATED']
        RETURN lps.flow_state AS state,
               avg(toFloat(lps.flow_confidence)) AS avg_conf
    """, P(pid_id))
    seeded_avg = next((r["avg_conf"] for r in conf_stats if r["state"] == "SEEDED"), None)
    prop_avg   = next((r["avg_conf"] for r in conf_stats if r["state"] == "PROPAGATED"), None)
    if seeded_avg and prop_avg:
        check(prop_avg < seeded_avg,
              "Propagated: avg confidence < SEEDED avg (BFS decay applied)",
              f"propagated={prop_avg:.3f}, seeded={seeded_avg:.3f}")
        info(f"  SEEDED avg_conf={seeded_avg:.3f}  PROPAGATED avg_conf={prop_avg:.3f}")

    return {"unreachable": unreachable, "bad_dir": bad_dir}


# ── 4. BLOCKED / HITL_PENDING ─────────────────────────────────────────────────

def check_blocked_hitl(session, pid_id: str, count_map: dict):
    blocked_count = count_map.get("BLOCKED", 0)
    hitl_count    = count_map.get("HITL_PENDING", 0)

    if blocked_count > 0:
        bad_src = scalar(session, """
            MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'BLOCKED'})
            WHERE lps.flow_source <> 'propagation_blocked'
            RETURN count(lps) AS c
        """, P(pid_id))
        check(bad_src == 0, "Blocked: flow_source = 'propagation_blocked'",
              f"{bad_src} wrong" if bad_src else "")
    else:
        check(True, "Blocked: no BLOCKED LPS (0 structural flaws)", "count=0")

    if hitl_count > 0:
        bad_hitl_src = scalar(session, """
            MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'HITL_PENDING'})
            WHERE lps.flow_source <> 'hitl_required'
            RETURN count(lps) AS c
        """, P(pid_id))
        check(bad_hitl_src == 0, "HITL_PENDING: flow_source = 'hitl_required'",
              f"{bad_hitl_src} wrong" if bad_hitl_src else "")

        no_conflict = scalar(session, """
            MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'HITL_PENDING'})
            WHERE NOT EXISTS {
                MATCH (a:Annotation {pid_id:$pid_id,
                                     pattern_type:'direction_conflict_observed'})
                      -[:ANNOTATES]->(lps)
            }
            RETURN count(lps) AS c
        """, P(pid_id))
        check(no_conflict == 0, "HITL_PENDING: all have direction_conflict_observed annotation",
              f"{no_conflict} missing annotation" if no_conflict else "")
    else:
        check(True, "HITL_PENDING: no unresolvable conflicts (count=0)", "count=0")


# ── 5. UNKNOWN ─────────────────────────────────────────────────────────────────

def check_unknown(session, pid_id: str, count_map: dict) -> dict:
    unknown_count = count_map.get("UNKNOWN", 0)
    info(f"UNKNOWN LPS: {unknown_count}")

    if unknown_count == 0:
        check(True, "Unknown: 0 unreachable LPS (full coverage achieved)", "")
        return {"unknown_count": 0}

    # 5a — UNKNOWN have no directional Evidence
    unknown_with_ev = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'UNKNOWN'})
        WHERE EXISTS {
            MATCH (lps)<-[:ABOUT]-(e:Evidence {pid_id:$pid_id})
            WHERE e.observed_direction IN ['FORWARD','REVERSE']
        }
        RETURN count(lps) AS c
    """, P(pid_id))
    check(unknown_with_ev == 0,
          "Unknown: no UNKNOWN LPS has directional Evidence",
          f"{unknown_with_ev} have Evidence" if unknown_with_ev else "")

    # 5b — flow_source = 'none'
    bad_src = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'UNKNOWN'})
        WHERE lps.flow_source <> 'none'
        RETURN count(lps) AS c
    """, P(pid_id))
    check(bad_src == 0, "Unknown: flow_source = 'none'",
          f"{bad_src} wrong" if bad_src else "")

    # 5c — flow_confidence = 0
    bad_conf = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'UNKNOWN'})
        WHERE coalesce(toFloat(lps.flow_confidence), -1.0) <> 0.0
        RETURN count(lps) AS c
    """, P(pid_id))
    check(bad_conf == 0, "Unknown: flow_confidence = 0.0",
          f"{bad_conf} non-zero" if bad_conf else "")

    # 5d — no SEEDED/PROPAGATED neighbour (genuinely isolated)
    not_isolated = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'UNKNOWN'})
        WHERE EXISTS {
            MATCH (lps)-[:ADJACENT_VIA_NODES]-(nb:LogicalPipeSegment {pid_id:$pid_id})
            WHERE nb.flow_state IN ['SEEDED','PROPAGATED']
        }
        RETURN count(lps) AS c
    """, P(pid_id))
    check(not_isolated == 0,
          "Unknown: no UNKNOWN LPS has a reachable SEEDED/PROPAGATED neighbour",
          f"{not_isolated} have reachable neighbour (BFS incomplete?)" if not_isolated else "")

    # Show which phase4_hint the UNKNOWN LPS have (Phase 3 diagnostic)
    unknown_patterns = rows(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'UNKNOWN'})
        RETURN coalesce(lps.phase4_hint, 'none') AS pt, count(DISTINCT lps) AS n
        ORDER BY n DESC
    """, P(pid_id))
    info(f"  phase4_hint on UNKNOWN LPS:")
    for r in unknown_patterns:
        info(f"    {r['pt']:<45} lps={r['n']}")

    return {"unknown_count": unknown_count, "not_isolated": not_isolated}


# ── 6. flow_confidence range ───────────────────────────────────────────────────

def check_confidence_range(session, pid_id: str):
    # 6a — active states: confidence in (0, 1]
    out_of_range = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.flow_state IN ['SEEDED','PROPAGATED']
          AND (toFloat(coalesce(lps.flow_confidence, 0.0)) <= 0.0
               OR toFloat(coalesce(lps.flow_confidence, 0.0)) > 1.0)
        RETURN count(lps) AS c
    """, P(pid_id))
    check(out_of_range == 0, "Confidence: SEEDED/PROPAGATED in range (0, 1]",
          f"{out_of_range} out of range" if out_of_range else "")

    # 6b — no null confidence on any LPS with flow_state
    null_conf = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.flow_state IS NOT NULL
          AND lps.flow_confidence IS NULL
        RETURN count(lps) AS c
    """, P(pid_id))
    check(null_conf == 0, "Confidence: no null flow_confidence where flow_state is set",
          f"{null_conf} null" if null_conf else "")


# ── 7. Phase 3 contract stamps ─────────────────────────────────────────────────

def check_p3_stamps(session, pid_id: str, count_map: dict):
    blocked_count = count_map.get("BLOCKED", 0)

    # 7a — phase4_blocked LPS should not reach PROPAGATED state.
    # SEEDED is acceptable: tanks and other equipment-adjacent LPS can be seeded
    # directly from an inlet/outlet even if they have an engineering violation flag.
    # Only PROPAGATED (flow passed THROUGH) indicates the block was bypassed.
    if blocked_count == 0:
        check(True,
              "P3 stamps: no phase4_blocked LPS reached PROPAGATED state",
              "blocked=0, query skipped")
    else:
        contaminated_blocked = scalar(session, """
            MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
            WHERE lps.phase4_blocked = true
              AND lps.flow_state = 'PROPAGATED'
            RETURN count(lps) AS c
        """, P(pid_id))
        check(contaminated_blocked == 0,
              "P3 stamps: no phase4_blocked LPS reached PROPAGATED state",
              f"{contaminated_blocked} contaminated" if contaminated_blocked else "")

    # 7b — LPS with directional issues have phase4_hint stamped
    hints_present = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id})-[:ANNOTATES]->(lps:LogicalPipeSegment)
        WHERE a.pattern_type IN [
            'direction_conflict_observed','lps_direction_unresolved',
            'lps_low_confidence_evidence','lps_weak_evidence_consensus',
            'direction_evidence_missing'
        ]
        AND lps.phase4_hint IS NULL
        RETURN count(DISTINCT lps) AS c
    """, P(pid_id))
    check(hints_present == 0,
          "P3 stamps: phase4_hint set on all LPS with directional issues",
          f"{hints_present} missing hint" if hints_present else "")

    # 7c — BLOCKED LPS with engineering-rule hints had propagation_blocked rarity annotation
    # LPS blocked purely for direction_evidence_missing (no arrows) don't need
    # a structural rarity annotation — they were blocked by FSM, not by Phase 3.
    if blocked_count > 0:
        no_rarity = scalar(session, """
            MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'BLOCKED'})
            WHERE lps.phase4_hint IS NOT NULL
              AND lps.phase4_hint <> 'direction_evidence_missing'
              AND NOT EXISTS {
                MATCH (r:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity',
                                     propagation_blocked:true})
                WHERE r.phase4_hint = lps.phase4_hint
              }
            RETURN count(lps) AS c
        """, P(pid_id))
        check(no_rarity == 0,
              "P3 stamps: engineering-blocked LPS had Phase 3 propagation_blocked rarity flag",
              f"{no_rarity} without rarity flag" if no_rarity else "")
    else:
        check(True, "P3 stamps: no BLOCKED LPS (propagation_blocked=0)", "")


# ── 8. Equipment node assignment ───────────────────────────────────────────────

def check_equipment(session, pid_id: str, count_map: dict):
    equip_total = scalar(session, """
        MATCH (n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE n.label IN $labels
        RETURN count(DISTINCT n) AS c
    """, {**P(pid_id), "labels": EQUIPMENT_NODE_LABELS})
    info(f"Equipment nodes (ENDPOINT_OF LPS): {equip_total}")

    if equip_total == 0:
        check(True, "Equipment: no equipment nodes connected to LPS", "count=0")
        return

    # 8a — assigned equipment have valid flow_state
    bad_state = scalar(session, """
        MATCH (n:Node {flow_source:'phase4_equipment_assignment'})
        WHERE n.label IN $labels
          AND NOT n.flow_state IN
              ['SEEDED','SEEDED_UNKNOWN','PROPAGATED','BLOCKED','UNKNOWN','HITL_PENDING']
        RETURN count(n) AS c
    """, {"labels": EQUIPMENT_NODE_LABELS})
    check(bad_state == 0, "Equipment: assigned nodes have valid flow_state",
          f"{bad_state} invalid" if bad_state else "")

    # 8b — assigned equipment have FORWARD, REVERSE, or null direction
    bad_dir = scalar(session, """
        MATCH (n:Node {flow_source:'phase4_equipment_assignment'})
        WHERE n.label IN $labels
          AND n.flow_direction IS NOT NULL
          AND NOT n.flow_direction IN ['FORWARD','REVERSE']
        RETURN count(n) AS c
    """, {"labels": EQUIPMENT_NODE_LABELS})
    check(bad_dir == 0, "Equipment: flow_direction FORWARD / REVERSE (or null)",
          f"{bad_dir} invalid" if bad_dir else "")

    # 8c — flow_source correct
    wrong_src = scalar(session, """
        MATCH (n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE n.label IN $labels
          AND n.flow_state IS NOT NULL
          AND n.flow_source <> 'phase4_equipment_assignment'
        RETURN count(DISTINCT n) AS c
    """, {**P(pid_id), "labels": EQUIPMENT_NODE_LABELS})
    check(wrong_src == 0, "Equipment: flow_source = 'phase4_equipment_assignment'",
          f"{wrong_src} wrong source" if wrong_src else "")

    # 8d — equipment flow_state matches the best (highest-confidence) ENDPOINT_OF LPS
    mismatch = scalar(session, """
        MATCH (n:Node {flow_source:'phase4_equipment_assignment'})
              -[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE n.label IN $labels
          AND lps.flow_state IN ['SEEDED','PROPAGATED']
          AND lps.flow_direction IN ['FORWARD','REVERSE']
        WITH n, lps
        ORDER BY toFloat(coalesce(lps.flow_confidence, 0.0)) DESC
        WITH n, collect(lps)[0] AS best
        WHERE best.flow_state <> n.flow_state
        RETURN count(DISTINCT n) AS c
    """, {**P(pid_id), "labels": EQUIPMENT_NODE_LABELS})
    check(mismatch == 0,
          "Equipment: flow_state matches best (highest-confidence) ENDPOINT_OF LPS",
          f"{mismatch} mismatched" if mismatch else "")

    # 8e — unassigned equipment connect only to non-directional LPS
    unassigned_has_directional = scalar(session, """
        MATCH (n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE n.label IN $labels
          AND n.flow_state IS NULL
          AND lps.flow_direction IN ['FORWARD','REVERSE']
        RETURN count(DISTINCT n) AS c
    """, {**P(pid_id), "labels": EQUIPMENT_NODE_LABELS})
    check(unassigned_has_directional == 0,
          "Equipment: unassigned nodes have no directional LPS available",
          f"{unassigned_has_directional} should have been assigned" if unassigned_has_directional else "")

    # Direction distribution
    dist = rows(session, """
        MATCH (n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE n.label IN $labels
        RETURN coalesce(n.flow_direction, 'unassigned') AS dir,
               count(DISTINCT n) AS n
        ORDER BY n DESC
    """, {**P(pid_id), "labels": EQUIPMENT_NODE_LABELS})
    for r in dist:
        info(f"  direction={r['dir']:<12} nodes={r['n']}")


# ── 9. Cross-PID isolation ─────────────────────────────────────────────────────

def check_isolation(session, pid_id: str):
    # 9a — no LPS from other PIDs got flow_state adjacent to this PID
    cross_lps = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
              -[:ADJACENT_VIA_NODES]-(nb:LogicalPipeSegment)
        WHERE nb.pid_id <> $pid_id
          AND nb.flow_state IS NOT NULL
        RETURN count(DISTINCT nb) AS c
    """, P(pid_id))
    check(cross_lps == 0,
          "Isolation: no foreign-PID LPS have flow_state adjacent to this PID",
          f"{cross_lps} cross-PID neighbours with flow_state" if cross_lps else "")

    # 9b — no Node has flow_source=phase4_equipment_assignment from wrong PID LPS
    contaminated_nodes = scalar(session, """
        MATCH (n:Node {pid_id:$pid_id, flow_source:'phase4_equipment_assignment'})
        WHERE NOT EXISTS {
            MATCH (n)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$pid_id})
        }
          AND EXISTS {
            MATCH (n)-[:ENDPOINT_OF]->(:LogicalPipeSegment)
        }
        RETURN count(n) AS c
    """, P(pid_id))
    check(contaminated_nodes == 0,
          "Isolation: no equipment node assigned from wrong-PID LPS",
          f"{contaminated_nodes} contaminated" if contaminated_nodes else "")


# ── 10. PID status + trace ─────────────────────────────────────────────────────

def check_status_trace(session, pid_id: str, lps_total: int):
    # 10a — PID status
    status_row = session.run(
        "MATCH (pid:PID {pid_id:$pid_id}) RETURN pid.status AS status",
        pid_id=pid_id,
    ).single()
    status = status_row["status"] if status_row else None
    _valid_post4 = {"PHASE4_COMPLETE", "PHASE5_COMPLETE", "PHASE6_COMPLETE", "PHASE7_COMPLETE"}
    check(status in _valid_post4,
          "Status: pid.status = 'PHASE4_COMPLETE'",
          f"status='{status}'" if status not in _valid_post4 else "")

    # 10b — trace file exists
    trace_path = Path(PROJECT_ROOT) / "logs" / f"phase4_trace_{pid_id}.json"
    check(trace_path.exists(),
          "Trace: logs/phase4_trace_{pid_id}.json exists",
          str(trace_path) if not trace_path.exists() else str(trace_path.name))

    # 10c — trace entry count matches lps_total
    if trace_path.exists():
        trace_data = json.loads(trace_path.read_text(encoding="utf-8"))
        trace_count = len(trace_data)
        check(trace_count == lps_total,
              "Trace: entry count == lps_total",
              f"trace={trace_count}, lps_total={lps_total}")

        from collections import Counter
        trace_states = Counter(v.get("state") for v in trace_data.values())
        info("  Trace state distribution (from file):")
        for state, n in trace_states.most_common():
            info(f"    {state:<22} {n}")


# ── Readiness gate ─────────────────────────────────────────────────────────────

def readiness_gate() -> bool:
    return len(_failures) == 0


# ── Config ─────────────────────────────────────────────────────────────────────

def load_neo4j_config():
    with open(os.path.join(PROJECT_ROOT, "config", "neo4j.yaml")) as f:
        return yaml.safe_load(f)["neo4j"]


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Verify Phase 4 FSM outputs for a PID."
    )
    parser.add_argument("--pid", required=True, help="PID ID to verify")
    args = parser.parse_args()
    pid_id = args.pid

    print(f"\n{'='*68}")
    print(f"  PHASE 4 VERIFICATION  |  PID={pid_id}")
    print(f"{'='*68}")

    loader = Neo4jLoader(load_neo4j_config())
    lps_total = 0

    try:
        with loader.driver.session(database=loader.database) as session:

            header("1. LPS FLOW_STATE COVERAGE")
            cov = check_coverage(session, pid_id)
            lps_total = cov["lps_total"]

            header("2. SEEDED / SEEDED_UNKNOWN")
            check_seeded(session, pid_id)

            header("3. PROPAGATED")
            check_propagated(session, pid_id, cov["count_map"])

            header("4. BLOCKED / HITL_PENDING")
            check_blocked_hitl(session, pid_id, cov["count_map"])

            header("5. UNKNOWN")
            check_unknown(session, pid_id, cov["count_map"])

            header("6. FLOW_CONFIDENCE RANGE")
            check_confidence_range(session, pid_id)

            header("7. PHASE 3 CONTRACT STAMPS")
            check_p3_stamps(session, pid_id, cov["count_map"])

            header("8. EQUIPMENT NODE ASSIGNMENT")
            check_equipment(session, pid_id, cov["count_map"])

            header("9. CROSS-PID ISOLATION")
            check_isolation(session, pid_id)

            header("10. PID STATUS + TRACE FILE")
            check_status_trace(session, pid_id, lps_total)

            header("PHASE 5 READINESS")
            total_checks = 37
            fail_count   = len(_failures)
            pass_count   = total_checks - fail_count

            print(f"\n  Checks passed : {pass_count}/{total_checks}")
            if _failures:
                print(f"  Failed checks :")
                for f in _failures:
                    print(f"    ❌ {f}")
            print()

            passed = readiness_gate()
            if passed:
                print(f"  ✅  Phase 5 READINESS: PASS  —  PID={pid_id} ready")
            else:
                print(f"  ❌  Phase 5 READINESS: FAIL  —  Fix issues above first")

    finally:
        loader.close()

    print(f"\n{'='*68}\n")
    sys.exit(0 if readiness_gate() else 1)


if __name__ == "__main__":
    main()