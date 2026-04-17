# scripts/run_phase7.py
#
# Phase 7 orchestrator — Human-in-the-Loop Approval + Corpus + Global Stats
#
# Usage:
#   python scripts/run_phase7.py --pid PID_2
#   python scripts/run_phase7.py --pid PID_2 --auto-approve
#   python scripts/run_phase7.py --pid PID_2 --auto-approve --force
#
# PREREQUISITES: pid.status == 'PHASE6_COMPLETE'
#
# EXECUTION ORDER:
#   1. Validate PID status (PHASE6_COMPLETE required)
#   2. Build HITL review queue (violations + high-severity rarity)
#   3. Present items for human review (or auto-approve with --auto-approve)
#   4. Write review decisions back to Neo4j (→ Global Registry feedback loop)
#   5. Build Per-Skid Corpus (cross-PID ESV normalization, if N≥2 PIDs)
#   6. Build Global Statistical Knowledge Layer (cross-skid aggregation)
#   7. Stamp pid.status = 'PHASE7_COMPLETE'
#
# ARCHITECTURE FLOWS IMPLEMENTED:
#   C11: Phase 6 → Phase 7 (traces + violations → human queue)
#   C12: Phase 7 → Global Registry (approved changes → graph update)
#   C16: Phase 3 → Per-Skid Corpus (via skid_corpus_rarity)
#   C17: Global Registry → Per-Skid Corpus (registry provides skid→PID mapping)
#   C18: Per-Skid Corpus → Global Statistical Knowledge Layer
#   C19: Global Statistical Knowledge Layer → Phase 4 (GlobalStatistic nodes readable)

import argparse
import json
import logging
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader
from engine.phase7_hitl.approval import Phase7HumanApproval
from engine.phase3_annotation.skid_corpus_rarity import build_skid_corpus
from engine.phase3_annotation.global_statistics import build_global_statistics


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


def clear_phase7_data(loader: Neo4jLoader, pid_id: str) -> None:
    """Clear Phase 7 review stamps from Annotations."""
    with loader.driver.session(database=loader.database) as s:
        s.run("""
            MATCH (a:Annotation {pid_id: $pid_id})
            WHERE a.hitl_status IS NOT NULL
            REMOVE a.hitl_status, a.reviewed_by,
                   a.review_note, a.rejection_reason, a.reviewed_at
        """, pid_id=pid_id)
        s.run("""
            MATCH (pid:PID {pid_id:$pid_id})
            SET pid.status = 'PHASE6_COMPLETE'
        """, pid_id=pid_id)
    logger.info("[PHASE7] Cleared Phase 7 review data for PID=%s", pid_id)


# ── Orchestrator ─────────────────────────────────────────────────────────────────

def run_phase7(pid_id: str, loader: Neo4jLoader, auto_approve: bool = False) -> None:
    logger.info("\n========== PHASE 7 START | PID=%s ==========\n", pid_id)

    # Resolve plant/skid for corpus and global stats
    with loader.driver.session(database=loader.database) as s:
        ctx = s.run("""
            MATCH (plant:Plant)-[:HAS_SKID]->(skid:Skid)
                  -[:HAS_PID]->(pid:PID {pid_id:$pid_id})
            RETURN plant.plant_id AS plant_id,
                   skid.skid_id   AS skid_id
        """, pid_id=pid_id).single()

    if ctx is None:
        raise ValueError(
            f"PID '{pid_id}' not found in Plant→Skid→PID hierarchy. "
            "Run register_pid.py first."
        )

    plant_id: str = ctx["plant_id"]
    skid_id: str = ctx["skid_id"]

    with loader.driver.session(database=loader.database) as session:

        # ── Step 1: Build HITL queue ──────────────────────────────────────────
        logger.info("[PHASE7] Step 1: Building HITL review queue")
        hitl = Phase7HumanApproval(session, pid_id)
        queue_size = hitl.build_queue()
        logger.info("[PHASE7]   Queue size: %d items", queue_size)

        # ── Step 2: Process queue ─────────────────────────────────────────────
        if queue_size > 0:
            if auto_approve:
                logger.info(
                    "[PHASE7] Step 2: Auto-approving %d items", queue_size
                )
                approved = hitl.auto_approve_all(reviewer="phase7_auto")
                logger.info("[PHASE7]   Auto-approved: %d", approved)
            else:
                logger.info(
                    "[PHASE7] Step 2: Interactive review (%d items)", queue_size
                )
                _interactive_review(hitl)
        else:
            logger.info("[PHASE7] Step 2: No items to review. Skipping.")

        summary = hitl.get_summary()

        # ── Step 3: Per-Skid Corpus (C16, C17) ───────────────────────────────
        logger.info("[PHASE7] Step 3: Building Per-Skid Corpus (skid=%s)", skid_id)
        corpus_result = build_skid_corpus(session, skid_id)

        # ── Step 4: Global Statistical Knowledge Layer (C18, C19) ─────────────
        logger.info(
            "[PHASE7] Step 4: Building Global Statistical Knowledge Layer "
            "(plant=%s)", plant_id
        )
        global_result = build_global_statistics(session, plant_id)

    # ── Step 5: Stamp PID status ──────────────────────────────────────────────
    with loader.driver.session(database=loader.database) as s:
        s.run("""
            MATCH (pid:PID {pid_id:$pid_id})
            SET pid.status = 'PHASE7_COMPLETE'
        """, pid_id=pid_id)

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("\n========== PHASE 7 SUMMARY | PID=%s ==========", pid_id)
    logger.info("  HITL queue total         : %d", summary["total"])
    for status, count in sorted(summary.get("by_status", {}).items()):
        logger.info("    %-22s %d", status, count)
    logger.info("  HITL by severity:")
    for sev, count in sorted(summary.get("by_severity", {}).items()):
        logger.info("    %-22s %d", sev, count)

    if corpus_result.get("skipped"):
        logger.info("  Per-Skid Corpus          : SKIPPED (need ≥2 PIDs)")
    else:
        logger.info(
            "  Per-Skid Corpus          : %d patterns across %d PIDs",
            corpus_result.get("patterns_updated", 0),
            corpus_result.get("pid_count", 0),
        )

    if global_result.get("skipped"):
        logger.info("  Global Statistics        : SKIPPED (%s)",
                     global_result.get("reason", "no data"))
    else:
        logger.info(
            "  Global Statistics        : %d patterns across %d PIDs / %d skids",
            global_result.get("patterns_created", 0),
            global_result.get("total_pids", 0),
            global_result.get("total_skids", 0),
        )

    logger.info("========== PHASE 7 COMPLETE | PID=%s ==========\n", pid_id)


# ── Interactive review ────────────────────────────────────────────────────────────

def _interactive_review(hitl: Phase7HumanApproval) -> None:
    """Present each queue item for interactive human review."""
    for i, item in enumerate(hitl.queue, 1):
        if item.status != "PENDING":
            continue
        print(f"\n--- Item {i}/{len(hitl.queue)} ---")
        print(f"  ID:       {item.item_id}")
        print(f"  PID:      {item.pid_id}")
        print(f"  Source:   {item.source}")
        print(f"  Pattern:  {item.pattern_type}")
        print(f"  Severity: {item.severity}")
        print(f"  Detail:   {item.description}")
        print()

        while True:
            choice = input("  [A]pprove / [R]eject / [S]kip ? ").strip().lower()
            if choice in ("a", "approve"):
                note = input("  Note (optional): ").strip()
                hitl.approve(item, reviewer="human", note=note)
                print(f"  → APPROVED")
                break
            elif choice in ("r", "reject"):
                reason = input("  Rejection reason: ").strip()
                hitl.reject(item, reviewer="human", reason=reason)
                print(f"  → REJECTED")
                break
            elif choice in ("s", "skip"):
                print(f"  → DEFERRED")
                break
            else:
                print("  Invalid choice. Enter A, R, or S.")


# ── Entry point ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Phase 7 Human-in-the-Loop Approval + Corpus + Global Stats."
    )
    parser.add_argument(
        "--pid",   required=True,
        help="PID ID as registered in Neo4j (e.g. PID_2)"
    )
    parser.add_argument(
        "--auto-approve", action="store_true",
        help="Auto-approve all HITL items (skip interactive review)"
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
            "[PHASE7] PID resolved: %s / %s / %s",
            info["plant_id"], info["skid_id"], args.pid
        )

        status = info["status"]

        if status not in {"PHASE6_COMPLETE", "PHASE7_COMPLETE"}:
            raise RuntimeError(
                f"PID '{args.pid}' has status='{status}'. "
                "Phase 7 requires PHASE6_COMPLETE. Run Phases 0→6 first."
            )

        if status == "PHASE7_COMPLETE":
            logger.warning(
                "\n[PHASE7] WARNING: PID=%s already has status='PHASE7_COMPLETE'.\n"
                "  Re-running clears review stamps on Annotations.\n",
                args.pid
            )
            if not args.force:
                answer = input("  Proceed with re-run? [y/N]: ").strip().lower()
                if answer != "y":
                    logger.info("[PHASE7] Aborted. No changes made.")
                    return
            clear_phase7_data(loader, args.pid)

        run_phase7(args.pid, loader, auto_approve=args.auto_approve)

    finally:
        loader.close()
        logger.info("[INFO] Neo4j connection closed.")


if __name__ == "__main__":
    main()
