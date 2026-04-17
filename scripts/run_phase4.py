# scripts/run_phase4.py
#
# Phase 4 orchestrator — Flow Resolution FSM + Equipment flow assignment
#
# Usage:
#   python scripts/run_phase4.py --pid PID_2
#   python scripts/run_phase4.py --pid PID_2 --force
#
# PREREQUISITES: pid.status == 'PHASE3_COMPLETE'
#
# EXECUTION ORDER:
#   0a. Pre-flight: validate Phase 3 contracts, stamp phase4_blocked/phase4_hint
#       on LPS from structural rarity annotations (propagation_blocked=true).
#   0b. Pre-flight (Phase 3.5): stamp phase4_blocked on LPS connected (via ENDPOINT_OF)
#       to equipment nodes bearing safety-critical engineering rule violations.
#   1.  Reset: clear flow_state on LPS for this PID
#   2.  Seed: weighted Evidence vote → flow_direction on LPS with Evidence
#   3.  Propagate: BFS over ADJACENT_VIA_NODES with decay
#   4.  Mark remaining: BLOCKED (structural flaw or safety rule) | UNKNOWN (unreachable)
#   5.  Assign: stamp flow_state onto equipment Node instances
#   5b. Stamp: engineering rule violation summaries onto equipment nodes (Phase 3.5)
#   6.  Trace: write logs/phase4_trace_{pid_id}.json
#   7.  Status: set pid.status = 'PHASE4_COMPLETE'
#
# CHANGES FROM OLD main_phase4.py:
#
#   [IMPORT]    engine.phase0_ingestion.load_to_neo4j (was ingestion.load_to_neo4j)
#   [IMPORT]    engine.phase4_fsm.* (was FSM.*)
#   [NO_PID]    --pid / --force args added (was unscoped global run)
#   [STATUS]    PHASE3_COMPLETE prereq check + PHASE4_COMPLETE stamp
#   [STEP]      ingest_equipment step REMOVED (Equipment nodes not in our schema)
#   [STEP]      fsm_core.run_fsm replaces ingest_phase4_fsm (Evidence-based seeding,
#               ADJACENT_VIA_NODES propagation, Phase 3 contract integration)
#   [STEP]      flow_assignment.assign_flow_to_nodes replaces ingest_phase4_flow
#               (targets Node instances via ENDPOINT_OF, not Equipment nodes)
#   [TRACE]     per-PID trace: logs/phase4_trace_{pid_id}.json
#   [ENG_RULES] clear_phase4_data now also removes Phase 3.5 violation summary
#               properties (has_rule_violations, rule_violation_count,
#               rule_violation_types) from equipment nodes.
#               The engineering_rule_violation Annotation nodes are Phase 3.5
#               data and are preserved.
#   [SUMMARY]   run_phase4 summary now logs Phase 3.5 integration counts
#               (eng_rule_blocked, rule_violations_stamped).

import argparse
import json
import logging
import os
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader
from engine.phase4_fsm.fsm_core import run_fsm
from engine.phase4_fsm.flow_assignment import assign_flow_to_nodes


# ── Config ──────────────────────────────────────────────────────────────────────

def load_neo4j_config() -> dict:
    with open(os.path.join(PROJECT_ROOT, "config", "neo4j.yaml")) as f:
        return yaml.safe_load(f)["neo4j"]


# ── PID lifecycle helpers ────────────────────────────────────────────────────────

def resolve_pid(loader: Neo4jLoader, pid_id: str) -> dict:
    with loader.driver.session(database=loader.database) as s:
        row = s.run("""
            MATCH (plant:Plant)-[:HAS_SKID]->(skid:Skid)
                  -[:HAS_PID]->(pid:PID {pid_id:$pid_id})
            RETURN plant.plant_id AS plant_id,
                   skid.skid_id   AS skid_id,
                   pid.status     AS status
        """, pid_id=pid_id).single()
    if row is None:
        raise ValueError(
            f"PID '{pid_id}' not found. Run register_pid.py first."
        )
    return dict(row)


def clear_phase4_data(loader: Neo4jLoader, pid_id: str) -> None:
    """
    Remove Phase 4 outputs for this PID.
    Phase 3 data (Evidence, Annotations, seed_confidence) is preserved.
    Phase 3.5 engineering_rule_violation Annotation nodes are preserved.

    Properties cleared on equipment Node instances:
      flow_state, flow_direction, flow_confidence, flow_source, flow_pid_id
      has_rule_violations, rule_violation_count, rule_violation_types

    Note: has_rule_violations / rule_violation_count / rule_violation_types are
    Phase 4 derived properties written by flow_assignment.stamp_rule_violations_on_nodes.
    The underlying engineering_rule_violation Annotation nodes are Phase 3.5 and
    are NOT removed here — they are only cleared by clear_phase3_data in run_phase3.py.
    """
    with loader.driver.session(database=loader.database) as s:
        # Remove flow state from LPS (including preflight stamps)
        s.run("""
            MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
            REMOVE lps.flow_state, lps.flow_direction,
                   lps.flow_confidence, lps.flow_source,
                   lps.phase4_blocked, lps.phase4_hint,
                   lps.phase4_resolution_rule
        """, pid_id=pid_id)

        # Remove flow state AND rule violation summaries from equipment Node instances.
        # Flow source 'phase4_equipment_assignment' identifies nodes written by Phase 4.
        # Rule violation summary properties (has_rule_violations etc.) are also Phase 4
        # derived — remove them even if the node somehow lost flow_source.
        s.run("""
            MATCH (n:Node {flow_source:'phase4_equipment_assignment'})
                  -[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$pid_id})
            REMOVE n.flow_state, n.flow_direction,
                   n.flow_confidence, n.flow_source,
                   n.flow_pid_id,
                   n.has_rule_violations, n.rule_violation_count,
                   n.rule_violation_types
        """, pid_id=pid_id)

        # Belt-and-suspenders: clear violation summary from any equipment node
        # in this PID that still carries has_rule_violations but lost flow_source
        # (e.g. from a partial earlier run).
        s.run("""
            MATCH (n:Node {has_rule_violations:true})
                  -[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$pid_id})
            REMOVE n.has_rule_violations, n.rule_violation_count,
                   n.rule_violation_types
        """, pid_id=pid_id)

        # Revert PID status
        s.run("""
            MATCH (pid:PID {pid_id:$pid_id})
            SET pid.status = 'PHASE3_COMPLETE'
        """, pid_id=pid_id)

    logger.info("[PHASE4] Cleared Phase 4 data for PID=%s", pid_id)


# ── Orchestrator ─────────────────────────────────────────────────────────────────

def run_phase4(pid_id: str, loader: Neo4jLoader) -> None:
    logger.info("\n========== PHASE 4 START | PID=%s ==========\n", pid_id)

    with loader.driver.session(database=loader.database) as session:

        # Steps 0–4 inside FSM:
        #   0a. pre-flight structural rarity blocks
        #   0b. pre-flight Phase 3.5 engineering rule violation blocks  ← NEW
        #   1.  reset
        #   2.  seed
        #   3.  propagate
        #   4.  mark remaining
        logger.info("[PHASE4] Steps 0–4: FSM (pre-flight / seed / propagate / mark)")
        fsm_result = run_fsm(session, pid_id)

        # Step 5: assign flow to equipment Node instances
        # Step 5b: stamp Phase 3.5 rule violation summaries                ← NEW
        logger.info(
            "[PHASE4] Step 5: flow assignment + rule violation summary to equipment nodes"
        )
        assign_result = assign_flow_to_nodes(session, pid_id)

    # Step 6: write per-PID trace
    trace_path = Path(PROJECT_ROOT) / "logs" / f"phase4_trace_{pid_id}.json"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(
        json.dumps(fsm_result.get("trace", {}), indent=2),
        encoding="utf-8",
    )
    logger.info("[PHASE4] Trace written: %s", trace_path)

    # Step 7: update PID status
    with loader.driver.session(database=loader.database) as s:
        s.run("""
            MATCH (pid:PID {pid_id:$pid_id})
            SET pid.status = 'PHASE4_COMPLETE'
        """, pid_id=pid_id)

    # ── Summary ────────────────────────────────────────────────────────────────
    pf  = fsm_result.get("preflight", {})
    lps = pf.get("lps_count", 0)

    logger.info("\n========== PHASE 4 SUMMARY | PID=%s ==========", pid_id)
    logger.info("  LPS total                       : %d", lps)
    logger.info("  LPS with directional seed       : %d  (%.1f%%)",
                pf.get("evidence_count", 0),
                100.0 * pf.get("evidence_count", 0) / max(lps, 1))
    logger.info("  LPS blocked (structural rarity) : %d",
                pf.get("blocked_count", 0))
    logger.info("  LPS blocked (eng rule violations): %d  ← Phase 3.5",
                pf.get("eng_rule_blocked", 0))
    logger.info("  LPS blocked (total)             : %d",
                pf.get("total_blocked", 0))
    logger.info("  Global stats adjustments        : %d  ← C19",
                pf.get("global_stats_applied", 0))
    logger.info("  FSM seeded                      : %d", fsm_result.get("seeded", 0))
    logger.info("  FSM HITL_PENDING                : %d", fsm_result.get("hitl_pending", 0))
    logger.info("  FSM propagated                  : %d", fsm_result.get("total_propagated", 0))
    logger.info("  FSM blocked                     : %d", fsm_result.get("blocked", 0))
    logger.info("  FSM unknown                     : %d", fsm_result.get("unknown", 0))
    logger.info("  Equipment nodes updated         : %d", assign_result.get("updated", 0))
    logger.info("  Equipment nodes unassigned      : %d", assign_result.get("unassigned", 0))
    logger.info("  Equipment nodes with violations : %d  ← Phase 3.5",
                assign_result.get("rule_violations_stamped", 0))

    # State distribution
    logger.info("  State distribution:")
    for r in fsm_result.get("state_dist", []):
        pct = 100.0 * int(r["n"]) / max(lps, 1)
        logger.info("    %-22s %4d  (%.1f%%)", r["state"], int(r["n"]), pct)

    logger.info("  Trace: %s", trace_path)
    logger.info("========== PHASE 4 COMPLETE | PID=%s ==========\n", pid_id)


# ── Entry point ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Phase 4 Flow Resolution FSM + equipment flow assignment."
    )
    parser.add_argument(
        "--pid",   required=True,
        help="PID ID as registered in Neo4j (e.g. PID_2)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip re-run confirmation prompt"
    )
    args = parser.parse_args()

    # Neo4jLoader() resolves credentials itself: config/neo4j.yaml then env vars
    # (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD) — no YAML read needed here.
    loader = Neo4jLoader()

    try:
        info = resolve_pid(loader, args.pid)
        logger.info(
            "[PHASE4] PID resolved: %s / %s / %s",
            info["plant_id"], info["skid_id"], args.pid
        )

        status = info["status"]

        _valid_pre4 = {"PHASE3_COMPLETE", "PHASE4_COMPLETE", "PHASE5_COMPLETE", "PHASE6_COMPLETE", "PHASE7_COMPLETE"}
        if status not in _valid_pre4:
            raise RuntimeError(
                f"PID '{args.pid}' has status='{status}'. "
                "Phase 4 requires PHASE3_COMPLETE. Run Phases 0→3 first."
            )

        if status in {"PHASE4_COMPLETE", "PHASE5_COMPLETE", "PHASE6_COMPLETE", "PHASE7_COMPLETE"}:
            logger.warning(
                "\n[PHASE4] WARNING: PID=%s already has status='PHASE4_COMPLETE'.\n"
                "  Re-running clears flow states on LPS and equipment nodes.\n"
                "  Phase 3 data (Evidence, Annotations, seed_confidence) is preserved.\n"
                "  Phase 3.5 engineering rule violation Annotations are preserved.\n",
                args.pid
            )
            if args.force:
                logger.info("[PHASE4] --force set. Clearing and re-running.")
            else:
                answer = input("  Proceed with re-run? [y/N]: ").strip().lower()
                if answer != "y":
                    logger.info("[PHASE4] Aborted. No changes made.")
                    return
            clear_phase4_data(loader, args.pid)

        run_phase4(args.pid, loader)

    finally:
        loader.close()
        logger.info("[INFO] Neo4j connection closed.")


if __name__ == "__main__":
    main()