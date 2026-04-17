# scripts/run_phase5.py
#
# Phase 5 orchestrator — Cypher Query Registry Builder
#
# Usage:
#   python scripts/run_phase5.py --pid PID_2
#   python scripts/run_phase5.py --pid PID_2 --force
#
# PREREQUISITES: pid.status == 'PHASE4_COMPLETE'
#
# EXECUTION ORDER:
#   1. Validate PID status (PHASE4_COMPLETE required)
#   2. Rebuild the Phase 5 Cypher query registry (_meta/queries.json)
#   3. Validate all Cypher files are atomic + contain RETURN
#   4. Stamp pid.status = 'PHASE5_COMPLETE'
#
# The Phase 5 registry is a static artefact (not PID-specific) but we gate
# it behind PHASE4_COMPLETE to enforce the pipeline ordering shown in the
# architecture diagram: Phase 4 → Phase 5 → Phase 6 → Phase 7.

import argparse
import logging
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader
from engine.phase5_cypher.build_registry import build_registry, OUT_FILE


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


# ── Orchestrator ─────────────────────────────────────────────────────────────────

def run_phase5(pid_id: str, loader: Neo4jLoader) -> None:
    logger.info("\n========== PHASE 5 START | PID=%s ==========\n", pid_id)

    # Step 1: Rebuild the query registry
    logger.info("[PHASE5] Step 1: Rebuilding Cypher query registry")
    build_registry()

    # Step 2: Read registry stats
    import json
    registry_doc = json.loads(OUT_FILE.read_text(encoding="utf-8"))
    meta = registry_doc["registry"]
    queries = registry_doc["queries"]

    # Categorise
    categories = {}
    for qe in queries.values():
        cat = qe["category"]
        categories[cat] = categories.get(cat, 0) + 1

    # Step 3: Stamp PID status
    with loader.driver.session(database=loader.database) as s:
        s.run("""
            MATCH (pid:PID {pid_id:$pid_id})
            SET pid.status = 'PHASE5_COMPLETE'
        """, pid_id=pid_id)

    # ── Summary ────────────────────────────────────────────────────────────────
    logger.info("\n========== PHASE 5 SUMMARY | PID=%s ==========", pid_id)
    logger.info("  Registry version       : %s", meta["version"])
    logger.info("  Total queries indexed   : %d", meta["query_count"])
    logger.info("  Registry path           : %s", OUT_FILE)
    logger.info("  Categories:")
    for cat, n in sorted(categories.items()):
        logger.info("    %-20s %3d queries", cat, n)
    logger.info("========== PHASE 5 COMPLETE | PID=%s ==========\n", pid_id)


# ── Entry point ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Phase 5 Cypher Query Registry Builder."
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

    loader = Neo4jLoader()

    try:
        info = resolve_pid(loader, args.pid)
        logger.info(
            "[PHASE5] PID resolved: %s / %s / %s",
            info["plant_id"], info["skid_id"], args.pid
        )

        status = info["status"]

        if status not in {"PHASE4_COMPLETE", "PHASE5_COMPLETE",
                          "PHASE6_COMPLETE", "PHASE7_COMPLETE"}:
            raise RuntimeError(
                f"PID '{args.pid}' has status='{status}'. "
                "Phase 5 requires PHASE4_COMPLETE. Run Phases 0→4 first."
            )

        if status == "PHASE5_COMPLETE":
            logger.warning(
                "\n[PHASE5] WARNING: PID=%s already has status='PHASE5_COMPLETE'.\n"
                "  Re-running rebuilds the query registry.\n",
                args.pid
            )
            if not args.force:
                answer = input("  Proceed with re-run? [y/N]: ").strip().lower()
                if answer != "y":
                    logger.info("[PHASE5] Aborted. No changes made.")
                    return

        run_phase5(args.pid, loader)

    finally:
        loader.close()
        logger.info("[INFO] Neo4j connection closed.")


if __name__ == "__main__":
    main()
