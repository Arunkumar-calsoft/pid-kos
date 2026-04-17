# scripts/run_phase0.py
#
# Phase 0 entry point.
#
# Usage:
#   python scripts/run_phase0.py --pid PID_2
#
# The script resolves all file paths from Neo4j — no hardcoded paths here.
# PID must be registered first via scripts/register_pid.py.
#
# FIXES APPLIED:
#   FIX-4 (original): Re-ingestion guard — prompts before proceeding when PID
#           already has a status beyond 'REGISTERED'.
#
# GAP-9 FIX (PHASE0_COMPLETE):
#   run_phase0.py now writes pid.status = 'PHASE0_COMPLETE' at the end of a
#   successful run.  Previously the PID stayed at 'IN_PROGRESS' permanently
#   after Phase 0 completed, making it impossible to distinguish a running
#   Phase 0 from a successfully finished one from the status alone.
#   run_phase1.py is updated to require PHASE0_COMPLETE (or IN_PROGRESS as
#   backward-compat fallback) as the prerequisite status.
#
# GAP-5 FIX (clear cascade):
#   When re-running Phase 0 on a PID that is already at PHASE1_COMPLETE or
#   beyond, clear_pid(cascade_phase='full') is called.  This removes all
#   downstream phase data (PS, LPS, Arrow, Evidence, Annotation, flow props)
#   in addition to the Node and AnnotationRequest nodes, preventing ghost
#   topology from dangling CONTAINS/ENDPOINT_OF relationships.

import argparse
import os
import sys
import yaml
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from engine.phase0_ingestion.parse_graphml   import parse_graphml
from engine.phase0_ingestion.normalize_nodes  import normalize_nodes
from engine.phase0_ingestion.phase0_verify   import verify_ground_truth
from engine.phase0_ingestion.load_to_neo4j   import Neo4jLoader


def load_configs():
    # Only loads storage config — Neo4jLoader() handles its own credential
    # resolution (config/neo4j.yaml → env var overrides: NEO4J_URI/USER/PASSWORD).
    storage_cfg_path = os.path.join(PROJECT_ROOT, "config", "storage.yaml")
    with open(storage_cfg_path, "r") as f:
        storage_cfg = yaml.safe_load(f)["storage"]
    return storage_cfg


def check_pid_status(loader, pid_id):
    with loader.driver.session(database=loader.database) as s:
        row = s.run(
            "MATCH (pid:PID {pid_id: $pid_id}) RETURN pid.status AS status",
            pid_id=pid_id,
        ).single()
    return row["status"] if row else None


def resolve_pid_paths(loader, pid_id, store_root):
    with loader.driver.session(database=loader.database) as s:
        row = s.run(
            """
            MATCH (plant:Plant)-[:HAS_SKID]->(skid:Skid)-[:HAS_PID]->(pid:PID {pid_id: $pid_id})
            RETURN pid.graphml_path AS graphml_rel,
                   pid.image_path   AS image_rel,
                   pid.rev          AS rev,
                   pid.date         AS date,
                   skid.skid_id     AS skid_id,
                   skid.skid_type   AS skid_type,
                   plant.plant_id   AS plant_id
            """,
            pid_id=pid_id,
        ).single()

    if row is None:
        raise ValueError(f"PID '{pid_id}' not found. Run register_pid.py first.")

    graphml_abs = os.path.join(store_root, row["graphml_rel"].replace("/", os.sep))
    image_abs   = os.path.join(store_root, row["image_rel"].replace("/", os.sep))

    if not os.path.exists(graphml_abs):
        raise FileNotFoundError(f"GraphML not found on disk: {graphml_abs}")
    if not os.path.exists(image_abs):
        raise FileNotFoundError(f"Image not found on disk: {image_abs}")

    print(f"[PHASE 0] PID resolved:")
    print(f"  Plant    : {row['plant_id']}")
    print(f"  Skid     : {row['skid_id']} ({row['skid_type']})")
    print(f"  PID      : {pid_id} Rev {row['rev']} {row['date']}")
    print(f"  GraphML  : {graphml_abs}")
    print(f"  Image    : {image_abs}")

    return {
        "graphml_path": graphml_abs,
        "image_path":   image_abs,
        "plant_id":     row["plant_id"],
        "skid_id":      row["skid_id"],
        "skid_type":    row["skid_type"],
    }


def main():
    parser = argparse.ArgumentParser(description="Run Phase 0 ingestion for a PID.")
    parser.add_argument("--pid",   required=True,       help="PID ID as registered in Neo4j")
    parser.add_argument("--force", action="store_true", help="Skip re-ingestion prompt and clear automatically")
    args = parser.parse_args()
    pid_id = args.pid

    print(f"========== PHASE 0 START | PID={pid_id} ==========")

    storage_cfg = load_configs()
    store_root = storage_cfg["store_root"]
    # Neo4jLoader() resolves credentials itself: config/neo4j.yaml then env vars
    # (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD) — no YAML read needed here.
    loader = Neo4jLoader()

    try:
        # ── Re-ingestion guard ────────────────────────────────────────────
        # Statuses indicating Phase 0 has already run successfully.
        # 'REGISTERED' → first run, safe to proceed directly.
        # 'IN_PROGRESS' → Phase 0 may have crashed; safe to re-run from Node level.
        already_ingested_statuses = {
            "PHASE0_COMPLETE",   # GAP-9: Phase 0 now writes this on success
            "PHASE1_COMPLETE",
            "PHASE2_COMPLETE",
            "PHASE3_COMPLETE",
            "PHASE4_COMPLETE",
            "PHASE5_COMPLETE",
            "PHASE6_COMPLETE",
            "PHASE7_COMPLETE",
        }
        # Statuses that indicate only Node-level data exists (Phase 1 not yet run)
        node_only_statuses = {"IN_PROGRESS", "PHASE0_COMPLETE"}

        current_status = check_pid_status(loader, pid_id)

        if current_status is None:
            raise ValueError(f"PID '{pid_id}' not found. Run register_pid.py first.")

        if current_status in already_ingested_statuses:
            # Determine cascade depth needed
            if current_status in node_only_statuses:
                cascade = "node_only"
                cascade_desc = "Node and AnnotationRequest data only"
            else:
                cascade = "full"
                cascade_desc = "all phase data (PS, LPS, Arrow, Evidence, Annotation, flow properties)"

            print(
                f"\n[PHASE 0] WARNING: PID={pid_id} already has status='{current_status}'.\n"
                f"  Re-ingesting will clear {cascade_desc}.\n"
                f"  Other PIDs are not affected.\n"
            )

            if args.force:
                print(f"[PHASE 0] --force flag set. Clearing (cascade={cascade}) and re-ingesting.")
                proceed = True
            else:
                answer = input("  Proceed with re-ingestion? [y/N]: ").strip().lower()
                proceed = answer == "y"

            if not proceed:
                print("[PHASE 0] Aborted. No changes made.")
                loader.close()
                return

            print(f"[PHASE 0] Clearing existing data (cascade={cascade}) for PID={pid_id}...")
            loader.clear_pid(pid_id, cascade_phase=cascade)
            print(f"[PHASE 0] Clear complete. Proceeding with fresh ingestion.")

        # status == 'REGISTERED' falls through here — first run, proceed normally

        # ── Resolve paths from Neo4j ──────────────────────────────────────
        ctx = resolve_pid_paths(loader, pid_id, store_root)

        # ── Parse ─────────────────────────────────────────────────────────
        nodes, edges = parse_graphml(ctx["graphml_path"])

        # ── Normalise + filter ────────────────────────────────────────────
        nodes = normalize_nodes(nodes)

        # ── Verify ───────────────────────────────────────────────────────
        report = verify_ground_truth(nodes, edges, ctx["image_path"])

        # ── Load ─────────────────────────────────────────────────────────
        loader.ensure_registry(
            plant_id=ctx["plant_id"],
            skid_id=ctx["skid_id"],
            skid_type=ctx["skid_type"],
            pid_id=pid_id,
        )

        loader.load_nodes(nodes, pid_id=pid_id)
        loader.load_edges(edges, pid_id=pid_id)
        loader.load_annotation_requests(anomalies=report["anomalies"], pid_id=pid_id)
        loader.summary_orphans(limit=30)

        # ── GAP-9: Write PHASE0_COMPLETE status ───────────────────────────
        # Previously Phase 0 ended at IN_PROGRESS, making it impossible to
        # distinguish a running Phase 0 from a completed one via status alone.
        with loader.driver.session(database=loader.database) as s:
            s.run(
                "MATCH (pid:PID {pid_id: $pid_id}) SET pid.status = 'PHASE0_COMPLETE'",
                pid_id=pid_id,
            )

    finally:
        loader.close()

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n========== PHASE 0 SUMMARY | PID={pid_id} ==========")
    print(f"  Nodes loaded      : {report['node_count']}")
    print(f"  Edges loaded      : {report['edge_count']}")
    print(f"  Annotation requests:")
    counts = Counter(a["type"] for a in report["anomalies"])
    if counts:
        for t, c in counts.items():
            print(f"    {t}: {c}")
    else:
        print("    none")
    print(f"========== PHASE 0 COMPLETE | PID={pid_id} ==========")


if __name__ == "__main__":
    main()