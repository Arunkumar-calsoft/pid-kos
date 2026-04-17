# scripts/run_phase2.py
#
# Phase 2 entry point — Flow Evidence Generation.
#
# Usage:
#   python scripts/run_phase2.py --pid PID_2
#   python scripts/run_phase2.py --pid PID_2 --force
#
# Responsibilities:
#   - Parse + normalize (reuses Phase 0 engine modules)
#   - Bind arrows to LogicalPipeSegments (scoped to pid_id)
#   - Compute bbox geometry alignment vectors
#   - Persist FLOW_EVIDENCE relationships to Neo4j (idempotent MERGE)
#   - Cache evidence to logs/phase2_evidence.json
#
# Does NOT assign final flow_direction. That is Phase 4 (FSM).
#
# FIX-5: Re-ingestion guard added. If PID already has PHASE2_COMPLETE status,
#         script warns and prompts before clearing FLOW_EVIDENCE and Arrow nodes
#         for this PID and re-running. Pass --force to skip prompt.
#
# FIX-6: pid_id now passed into assign_flow_direction for DB query scoping
#         and Arrow node pid_id stamping.

import argparse
import os
import sys
import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from engine.phase0_ingestion.parse_graphml   import parse_graphml
from engine.phase0_ingestion.normalize_nodes  import normalize_nodes
from engine.phase0_ingestion.load_to_neo4j   import Neo4jLoader

from engine.phase2_flow.assign_flow_direction import assign_flow_direction
from engine.phase2_flow.symbol_dictionary     import SYMBOL_DICTIONARY

SAMPLE_DEBUG = 5


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


def clear_phase2_data(loader, pid_id):
    """
    Remove all Phase 2 data for this PID:
    Arrow nodes and FLOW_EVIDENCE relationships.
    Phase 0 and Phase 1 data is preserved.
    Uses dual-strategy: via relationship AND via pid_id property.
    """
    with loader.driver.session(database=loader.database) as s:
        # FLOW_EVIDENCE rels — via Arrow pid_id property
        s.run(
            """
            MATCH (a:Arrow {pid_id: $pid_id})-[r:FLOW_EVIDENCE]->()
            DELETE r
            """,
            pid_id=pid_id,
        )
        # Arrow nodes — via pid_id property
        s.run(
            "MATCH (a:Arrow {pid_id: $pid_id}) DETACH DELETE a",
            pid_id=pid_id,
        )
        # Reset PID status to PHASE1_COMPLETE so Phase 2 can re-run cleanly
        s.run(
            "MATCH (pid:PID {pid_id: $pid_id}) SET pid.status = 'PHASE1_COMPLETE'",
            pid_id=pid_id,
        )
    print(f"[PHASE 2] Cleared Arrow nodes and FLOW_EVIDENCE for PID={pid_id}")


def resolve_pid_paths(loader, pid_id, store_root):
    with loader.driver.session(database=loader.database) as s:
        row = s.run(
            """
            MATCH (plant:Plant)-[:HAS_SKID]->(skid:Skid)-[:HAS_PID]->(pid:PID {pid_id: $pid_id})
            RETURN pid.graphml_path AS graphml_rel,
                   pid.image_path   AS image_rel,
                   plant.plant_id   AS plant_id,
                   skid.skid_id     AS skid_id
            """,
            pid_id=pid_id,
        ).single()

    if row is None:
        raise ValueError(f"PID '{pid_id}' not found. Run register_pid.py first.")

    graphml_abs = os.path.join(store_root, row["graphml_rel"].replace("/", os.sep))
    image_abs   = os.path.join(store_root, row["image_rel"].replace("/", os.sep))

    if not os.path.exists(graphml_abs):
        raise FileNotFoundError(f"GraphML not found: {graphml_abs}")
    if not os.path.exists(image_abs):
        raise FileNotFoundError(f"Image not found: {image_abs}")

    print(f"[PHASE 2] PID resolved: {row['plant_id']} / {row['skid_id']} / {pid_id}")
    print(f"  GraphML : {graphml_abs}")
    print(f"  Image   : {image_abs}")
    return graphml_abs, image_abs


def check_phase1_complete(loader, pid_id):
    """
    Verify Phase 1 has been run before Phase 2.
    Raises if LPS count is 0 — Phase 2 has nothing to bind arrows to.
    """
    with loader.driver.session(database=loader.database) as s:
        row = s.run(
            "MATCH (lps:LogicalPipeSegment {pid_id: $pid_id}) RETURN count(lps) AS cnt",
            pid_id=pid_id,
        ).single()
    cnt = row["cnt"] if row else 0
    if cnt == 0:
        raise RuntimeError(
            f"[PHASE 2] No LogicalPipeSegments found for PID={pid_id}. "
            f"Run Phase 1 first."
        )
    print(f"[PHASE 2] Phase 1 check passed — {cnt} LPS found for PID={pid_id}")


def debug_nodes_sample(nodes, sample=5):
    print(f"[DEBUG] First {sample} nodes:")
    for n in nodes[:sample]:
        print(f"  {n['id']} | label={n.get('attrs', {}).get('label')} | attrs={n.get('attrs')}")


def main():
    parser = argparse.ArgumentParser(description="Run Phase 2 flow evidence generation.")
    parser.add_argument("--pid",          required=True,       help="PID ID as registered in Neo4j")
    parser.add_argument("--visual-debug", action="store_true", help="Write debug overlay PNG")
    parser.add_argument("--force",        action="store_true", help="Skip re-ingestion prompt and clear automatically")
    args = parser.parse_args()
    pid_id = args.pid

    print(f"========== PHASE 2 START | PID={pid_id} ==========")

    storage_cfg = load_configs()
    store_root = storage_cfg["store_root"]

    # Neo4jLoader() resolves credentials itself: config/neo4j.yaml then env vars
    # (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD) — no YAML read needed here.
    loader = Neo4jLoader()
    try:
        # ── FIX-5: Re-ingestion guard ─────────────────────────────────────
        already_ingested_statuses = {
            "PHASE2_COMPLETE",
            "PHASE3_COMPLETE",
            "PHASE4_COMPLETE",
            "PHASE5_COMPLETE",
            "PHASE6_COMPLETE",
            "PHASE7_COMPLETE",
        }

        current_status = check_pid_status(loader, pid_id)

        if current_status is None:
            raise ValueError(f"PID '{pid_id}' not found. Run register_pid.py first.")

        if current_status == "REGISTERED":
            raise RuntimeError(
                f"PID '{pid_id}' has status=REGISTERED. "
                f"Run Phase 0 and Phase 1 first."
            )

        if current_status == "IN_PROGRESS":
            raise RuntimeError(
                f"PID '{pid_id}' has status=IN_PROGRESS. "
                f"Phase 1 may not have completed. Check Phase 1 output."
            )

        if current_status in already_ingested_statuses:
            print(
                f"\n[PHASE 2] WARNING: PID={pid_id} already has "
                f"status='{current_status}'.\n"
                f"  Re-running will clear all Arrow nodes and FLOW_EVIDENCE "
                f"relationships for this PID.\n"
                f"  Phase 0 and Phase 1 data is preserved.\n"
            )

            if args.force:
                print("[PHASE 2] --force flag set. Clearing and re-running.")
                proceed = True
            else:
                answer = input("  Proceed with re-run? [y/N]: ").strip().lower()
                proceed = answer == "y"

            if not proceed:
                print("[PHASE 2] Aborted. No changes made.")
                loader.close()
                return

            clear_phase2_data(loader, pid_id)

        # ── Verify Phase 1 prerequisite ───────────────────────────────────
        check_phase1_complete(loader, pid_id)

        # ── Resolve paths ─────────────────────────────────────────────────
        graphml_path, image_path = resolve_pid_paths(loader, pid_id, store_root)

        # ── Parse + Normalize ─────────────────────────────────────────────
        nodes, edges = parse_graphml(graphml_path)
        print(f"[INFO] Parsed {len(nodes)} nodes, {len(edges)} edges")
        nodes = normalize_nodes(nodes)
        print(f"[INFO] Normalized: {len(nodes)} nodes")
        debug_nodes_sample(nodes, SAMPLE_DEBUG)

        # ── Flow evidence generation (FIX-6: pid_id passed in) ───────────
        assign_flow_direction(
            nodes,
            edges,
            loader,
            pid_id=pid_id,
            symbol_dict=SYMBOL_DICTIONARY,
            image_path=image_path,
            visual_debug=args.visual_debug,
            write_to_db=True,
        )

        # ── Update PID status ─────────────────────────────────────────────
        with loader.driver.session(database=loader.database) as session:
            session.run(
                "MATCH (pid:PID {pid_id: $pid_id}) SET pid.status = 'PHASE2_COMPLETE'",
                pid_id=pid_id,
            )

    finally:
        loader.close()
        print("[INFO] Neo4j connection closed.")

    print(f"========== PHASE 2 END | PID={pid_id} ==========")


if __name__ == "__main__":
    main()