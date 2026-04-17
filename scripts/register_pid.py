# scripts/register_pid.py
#
# One-time registration script. Run this ONCE per PID before the engine
# can process it. Establishes the Plant → Skid → PID hierarchy in Neo4j
# and records where the source files live on disk.
#
# Usage:
#   python scripts/register_pid.py \
#       --plant-id   PLANT_001 \
#       --plant-name "Energy Impact Center" \
#       --skid-id    SKID_01 \
#       --skid-type  CONDENSATE \
#       --pid-id     PID_2 \
#       --graphml    PLANT_001/SKID_01/PID_2/2.graphml \
#       --image      PLANT_001/SKID_01/PID_2/2.png \
#       --rev        A \
#       --date       2020-09-01
#
# Paths passed via --graphml and --image are RELATIVE to storage.store_root.
# The engine resolves them at runtime by joining store_root + relative_path.

import argparse
import os
import sys
import yaml

# ── Path resolution ────────────────────────────────────────────────────────
# scripts/ is one level below project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from neo4j import GraphDatabase


def load_configs():
    # Only loads storage config — neo4j credentials resolved separately with env var support.
    storage_cfg_path = os.path.join(PROJECT_ROOT, "config", "storage.yaml")
    with open(storage_cfg_path, "r") as f:
        storage_cfg = yaml.safe_load(f)["storage"]
    return storage_cfg


def _load_neo4j_cfg_with_env_override() -> dict:
    """
    Load neo4j credentials from config/neo4j.yaml then apply env var overrides.
    Environment variables NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD take priority.
    """
    neo4j_cfg_path = os.path.join(PROJECT_ROOT, "config", "neo4j.yaml")
    with open(neo4j_cfg_path, "r") as f:
        cfg = dict(yaml.safe_load(f)["neo4j"])   # copy so we don't mutate the yaml cache
    _env_uri      = os.environ.get("NEO4J_URI")
    _env_user     = os.environ.get("NEO4J_USER")
    _env_password = os.environ.get("NEO4J_PASSWORD")
    if _env_uri:      cfg["uri"]      = _env_uri
    if _env_user:     cfg["user"]     = _env_user
    if _env_password: cfg["password"] = _env_password
    return cfg


def validate_paths(store_root, graphml_rel, image_rel):
    """
    Verify source files exist on disk before registering.
    Paths are relative to store_root.
    """
    graphml_abs = os.path.join(store_root, graphml_rel)
    image_abs   = os.path.join(store_root, image_rel)

    errors = []
    if not os.path.exists(graphml_abs):
        errors.append(f"GraphML not found: {graphml_abs}")
    if not os.path.exists(image_abs):
        errors.append(f"Image not found:   {image_abs}")

    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        raise FileNotFoundError(
            "Source files missing. Place files in pid_store/ first."
        )

    print(f"[REGISTER] GraphML verified: {graphml_abs}")
    print(f"[REGISTER] Image verified:   {image_abs}")

    return graphml_abs, image_abs


def register(neo4j_cfg, plant_id, plant_name, skid_id, skid_type,
             pid_id, graphml_rel, image_rel, rev, date):

    driver = GraphDatabase.driver(
        neo4j_cfg["uri"],
        auth=(neo4j_cfg["user"], neo4j_cfg["password"]),
    )

    try:
        with driver.session(database=neo4j_cfg["database"]) as s:

            # Check if PID already registered
            existing = s.run(
                "MATCH (pid:PID {pid_id: $pid_id}) RETURN pid.pid_id AS id",
                pid_id=pid_id,
            ).single()

            if existing:
                print(f"[REGISTER] WARNING: PID '{pid_id}' already registered.")
                print(f"[REGISTER] Use --force to overwrite (not implemented yet).")
                return

            s.run(
                """
                MERGE (plant:Plant {plant_id: $plant_id})
                  ON CREATE SET plant.name = $plant_name

                MERGE (skid:Skid {skid_id: $skid_id})
                  ON CREATE SET skid.skid_type = $skid_type,
                                skid.plant_id  = $plant_id

                MERGE (pid:PID {pid_id: $pid_id})
                  SET pid.graphml_path = $graphml_rel,
                      pid.image_path   = $image_rel,
                      pid.rev          = $rev,
                      pid.date         = $date,
                      pid.status       = 'REGISTERED'

                MERGE (plant)-[:HAS_SKID]->(skid)
                MERGE (skid)-[:HAS_PID]->(pid)
                """,
                plant_id=plant_id,
                plant_name=plant_name,
                skid_id=skid_id,
                skid_type=skid_type,
                pid_id=pid_id,
                graphml_rel=graphml_rel.replace("\\", "/"),
                image_rel=image_rel.replace("\\", "/"),
                rev=rev,
                date=date,
            )

        print(f"[REGISTER] Registered successfully:")
        print(f"  Plant : {plant_id} ({plant_name})")
        print(f"  Skid  : {skid_id} ({skid_type})")
        print(f"  PID   : {pid_id} (Rev {rev}, {date})")
        print(f"  GraphML: {graphml_rel}")
        print(f"  Image  : {image_rel}")
        print(f"[REGISTER] Run engine with: python scripts/run_phase0.py --pid {pid_id}")

    finally:
        driver.close()


def main():
    parser = argparse.ArgumentParser(
        description="Register a PID in the KOS engine hierarchy."
    )
    parser.add_argument("--plant-id",   required=True)
    parser.add_argument("--plant-name", required=True)
    parser.add_argument("--skid-id",    required=True)
    parser.add_argument("--skid-type",  required=True)
    parser.add_argument("--pid-id",     required=True)
    parser.add_argument("--graphml",    required=True,
                        help="Path relative to storage.store_root")
    parser.add_argument("--image",      required=True,
                        help="Path relative to storage.store_root")
    parser.add_argument("--rev",        default="A")
    parser.add_argument("--date",       default="")

    args = parser.parse_args()

    neo4j_cfg, storage_cfg = _load_neo4j_cfg_with_env_override(), load_configs()
    store_root = storage_cfg["store_root"]

    validate_paths(store_root, args.graphml, args.image)

    register(
        neo4j_cfg=neo4j_cfg,
        plant_id=args.plant_id,
        plant_name=args.plant_name,
        skid_id=args.skid_id,
        skid_type=args.skid_type,
        pid_id=args.pid_id,
        graphml_rel=args.graphml,
        image_rel=args.image,
        rev=args.rev,
        date=args.date,
    )


if __name__ == "__main__":
    main()