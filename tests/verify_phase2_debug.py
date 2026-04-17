# tests/verify_phase2_debug.py
#
# PHASE 2 — Verification Only (READ-ONLY / INSPECTION)
#
# Changes from pid_kos version:
#   - from ingestion.load_to_neo4j → from engine.phase0_ingestion.load_to_neo4j
#   - Neo4jLoader() no args → Neo4jLoader(neo4j_cfg) loaded from config/neo4j.yaml
#   - Section 2: MATCH (a:Node) WHERE a.label='arrow' → MATCH (a:Arrow)
#     Phase 2 creates :Arrow nodes (separate label), not :Node{label:'arrow'}
#   - Section 4: MATCH (a:Node) → MATCH (a:Arrow) — same fix

import os
import sys
import yaml
from typing import Any, Dict, List, Optional

from neo4j.exceptions import Neo4jError

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader


# ── Utilities ─────────────────────────────────────────────────────────────

def info(msg):  print(f"[VERIFY] {msg}")
def warn(msg):  print(f"[WARN]   {msg}")
def header(t):  print("\n" + "=" * 80 + f"\n{t}\n" + "=" * 80)


def safe_single_value(session, query, params=None, key="c"):
    try:
        record = session.run(query, params or {}).single()
        if record:
            v = record.get(key)
            return int(v) if v is not None else 0
        return 0
    except Neo4jError as e:
        print(f"[ERROR] Query failed: {e}")
        raise


def safe_list(session, query, params=None):
    try:
        return session.run(query, params or {}).data()
    except Neo4jError as e:
        print(f"[ERROR] Query failed: {e}")
        raise


def property_key_exists(session, prop_name):
    return safe_single_value(
        session,
        "CALL db.propertyKeys() YIELD propertyKey WHERE propertyKey = $p RETURN count(*) AS c",
        {"p": prop_name},
    ) > 0


def relationship_type_exists(session, rel_type):
    return safe_single_value(
        session,
        "CALL db.relationshipTypes() YIELD relationshipType WHERE relationshipType = $t RETURN count(*) AS c",
        {"t": rel_type},
    ) > 0


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("========== PHASE 2 VERIFICATION START ==========")

    neo4j_cfg_path = os.path.join(PROJECT_ROOT, "config", "neo4j.yaml")
    with open(neo4j_cfg_path) as f:
        neo4j_cfg = yaml.safe_load(f)["neo4j"]

    loader = Neo4jLoader(neo4j_cfg)

    try:
        with loader.driver.session(database=loader.database) as session:

            # ── 0. Pipe & Logical Segment Presence ────────────────────────
            header("0. PIPE & LOGICAL SEGMENT PRESENCE")

            ps_count  = safe_single_value(session, "MATCH (ps:PipeSegment) RETURN count(ps) AS c")
            lps_count = safe_single_value(session, "MATCH (lps:LogicalPipeSegment) RETURN count(lps) AS c")
            info(f"PipeSegments present        : {ps_count}")
            info(f"LogicalPipeSegments present : {lps_count}")
            if ps_count == 0 or lps_count == 0:
                warn("Missing PipeSegment or LogicalPipeSegment — Phase 1/2 may be incomplete")

            # ── 1. Assertion Safety Check ─────────────────────────────────
            header("1. ASSERTION SAFETY CHECK (NO FLOW ASSERTIONS)")

            if property_key_exists(session, "flow_direction"):
                assigned = safe_single_value(session, """
                    MATCH (lps:LogicalPipeSegment)
                    WHERE lps.flow_direction IS NOT NULL
                    RETURN count(lps) AS c
                """)
                if assigned > 0:
                    warn(f"{assigned} LogicalPipeSegments already have flow_direction — violates Phase 2 contract")
                else:
                    info("No flow_direction assigned on LogicalPipeSegments — OK")
            else:
                info("flow_direction property not present — correct for Phase 2")

            # ── 2. Arrow Evidence Presence ────────────────────────────────
            header("2. ARROW FLOW EVIDENCE CHECK")

            # Phase 2 creates :Arrow nodes (separate label), not :Node{label:'arrow'}
            arrow_count = safe_single_value(session, "MATCH (a:Arrow) RETURN count(a) AS c")
            info(f"Arrow nodes (:Arrow label)  : {arrow_count}")
            if arrow_count == 0:
                warn("No :Arrow nodes found — Phase 2 may not have run or wrote no evidence")

            has_evidence = relationship_type_exists(session, "FLOW_EVIDENCE")
            if not has_evidence:
                warn("FLOW_EVIDENCE relationship type not present — evidence may be JSON-only")
            else:
                ev_count = safe_single_value(session, "MATCH ()-[r:FLOW_EVIDENCE]->() RETURN count(r) AS c")
                info(f"FLOW_EVIDENCE relationships : {ev_count}")

                # Direction breakdown
                fwd = safe_single_value(session, """
                    MATCH ()-[r:FLOW_EVIDENCE]->()
                    WHERE r.direction_hint = 'FORWARD'
                    RETURN count(r) AS c
                """)
                rev = safe_single_value(session, """
                    MATCH ()-[r:FLOW_EVIDENCE]->()
                    WHERE r.direction_hint = 'REVERSE'
                    RETURN count(r) AS c
                """)
                unk = safe_single_value(session, """
                    MATCH ()-[r:FLOW_EVIDENCE]->()
                    WHERE r.direction_hint = 'UNKNOWN'
                    RETURN count(r) AS c
                """)
                low = safe_single_value(session, """
                    MATCH ()-[r:FLOW_EVIDENCE]->()
                    WHERE r.low_confidence = true
                    RETURN count(r) AS c
                """)
                info(f"  FORWARD={fwd} | REVERSE={rev} | UNKNOWN={unk} | LOW_CONF={low}")

            # ── 3. Evidence Coverage ──────────────────────────────────────
            header("3. EVIDENCE COVERAGE / SUSPICIOUS SEGMENTS")

            uncovered = safe_single_value(session, """
                MATCH (lps:LogicalPipeSegment)
                WHERE NOT (lps)<-[:FLOW_EVIDENCE]-()
                RETURN count(lps) AS c
            """)
            info(f"LogicalPipeSegments without arrow evidence: {uncovered}")

            if uncovered > 0:
                warn("Some LogicalPipeSegments have no arrow evidence (valid or needs review)")
                sample = safe_list(session, """
                    MATCH (lps:LogicalPipeSegment)
                    WHERE NOT (lps)<-[:FLOW_EVIDENCE]-()
                    RETURN lps.id AS id
                    LIMIT 10
                """)
                print("[DEBUG] Sample uncovered LPS:")
                for r in sample:
                    print(f"  {r['id']}")

            # ── 4. Multi-Arrow Conflict Check ─────────────────────────────
            header("4. MULTI-ARROW CONFLICT CHECK")

            # :Arrow nodes (not :Node) — Phase 2 MERGE creates Arrow label
            conflicts = safe_list(session, """
                MATCH (lps:LogicalPipeSegment)<-[:FLOW_EVIDENCE]-(a:Arrow)
                WITH lps, count(a) AS arrows
                WHERE arrows > 1
                RETURN lps.id AS id, arrows
                ORDER BY arrows DESC
                LIMIT 10
            """)
            if conflicts:
                warn("LogicalPipeSegments with multiple FLOW_EVIDENCE entries (FSM resolution required):")
                for r in conflicts:
                    print(f"  {r['id']} | arrows={r['arrows']}")
            else:
                info("No multi-arrow conflicts — each LPS has at most one FLOW_EVIDENCE")

            # ── 5. Sample Evidence Detail ─────────────────────────────────
            header("5. SAMPLE FLOW_EVIDENCE DETAIL")

            sample_ev = safe_list(session, """
                MATCH (a:Arrow)-[r:FLOW_EVIDENCE]->(lps:LogicalPipeSegment)
                RETURN a.id AS arrow_id,
                       lps.id AS lps_id,
                       r.direction_hint AS direction,
                       r.cosine_alignment AS cosine,
                       r.confidence AS confidence,
                       r.low_confidence AS low_conf
                ORDER BY r.confidence DESC
                LIMIT 10
            """)
            print("[DEBUG] Top 10 FLOW_EVIDENCE by confidence:")
            for r in sample_ev:
                print(
                    f"  {r['arrow_id']} → {r['lps_id']} | "
                    f"dir={r['direction']} cos={r['cosine']} "
                    f"conf={r['confidence']} low={r['low_conf']}"
                )

        info("Phase 2 verification complete.")

    finally:
        loader.close()

    print("========== PHASE 2 VERIFICATION COMPLETE ==========")


if __name__ == "__main__":
    main()