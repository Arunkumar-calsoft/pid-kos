# scripts/run_phase6.py
#
# Phase 6 orchestrator — Reasoning Trace Generation
#
# Usage:
#   python scripts/run_phase6.py --pid PID_2
#   python scripts/run_phase6.py --pid PID_2 --force
#
# PREREQUISITES: pid.status == 'PHASE5_COMPLETE'
#
# EXECUTION ORDER:
#   1. Validate PID status (PHASE5_COMPLETE required)
#   2. Load Phase 5 query registry (_meta/queries.json)
#   3. Execute each verified query through Phase5Adapter
#   4. Build reasoning traces per category
#   5. Write trace JSON files to engine/phase6_trace/traces/
#   6. Update _global_index.json and per-category _index.json
#   7. Stamp pid.status = 'PHASE6_COMPLETE'
#
# Traces are deterministic: same graph state → same trace output.
# Each category (topology, valves, instruments, etc.) gets its own
# trace file under engine/phase6_trace/traces/<category>/.

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader
from engine.phase6_trace.builder.trace_builder import TraceBuilder, VALID_CATEGORIES
from engine.phase6_trace.adapters.phase5_adapter import Phase5Adapter
from engine.phase6_trace.utils.time import current_utc_time

PHASE5_DIR = Path(PROJECT_ROOT) / "engine" / "phase5_cypher"
REGISTRY_FILE = PHASE5_DIR / "_meta" / "queries.json"
TRACES_DIR = Path(PROJECT_ROOT) / "engine" / "phase6_trace" / "traces"

# Map Phase 5 categories to Phase 6 trace categories (VALID_CATEGORIES)
_CATEGORY_TO_TRACE = {
    "directionality":          "directionality",
    "external":                "external_interfaces",
    "instruments":             "instruments",
    "inventory":               "inventory",
    "lines":                   "lines",
    "quality":                 "quality",
    "reachability":            "reachability",
    "redundancy":              "redundancy",
    "topology":                "topology",
    "valves":                  "valves",
    "annotations":             "annotations",
    "cross_domain":            "cross_domain",
    "engineering_correctness": "engineering_correctness",
    "equipment_semantics":     "equipment_semantics",
    "flow_coverage":           "flow_coverage",
    "flow_nodes":              "flow_nodes",
    "pipe_edges":              "pipe_edges",
}


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


def clear_phase6_data(loader: Neo4jLoader, pid_id: str) -> None:
    """Revert PID status. Trace files are overwritten on re-run."""
    with loader.driver.session(database=loader.database) as s:
        s.run("""
            MATCH (pid:PID {pid_id:$pid_id})
            SET pid.status = 'PHASE5_COMPLETE'
        """, pid_id=pid_id)
    logger.info("[PHASE6] Reverted PID=%s status to PHASE5_COMPLETE", pid_id)


# ── Orchestrator ─────────────────────────────────────────────────────────────────

def run_phase6(pid_id: str, loader: Neo4jLoader) -> None:
    logger.info("\n========== PHASE 6 START | PID=%s ==========\n", pid_id)

    # Step 1: Load registry
    if not REGISTRY_FILE.exists():
        raise FileNotFoundError(
            f"Phase 5 registry not found: {REGISTRY_FILE}. Run Phase 5 first."
        )
    registry_doc = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    queries = registry_doc["queries"]
    verified = {qid: qe for qid, qe in queries.items() if qe.get("verified")}
    logger.info("[PHASE6] Loaded %d verified queries from registry", len(verified))

    # Step 2: Group queries by trace category
    by_category = defaultdict(list)
    for qid, qe in verified.items():
        p5_cat = qe["category"]
        trace_cat = _CATEGORY_TO_TRACE.get(p5_cat)
        if trace_cat and trace_cat in VALID_CATEGORIES:
            by_category[trace_cat].append(qe)

    # Step 3: Execute queries and build traces per category
    total_traces = 0
    total_rows = 0
    total_errors = 0
    category_summaries = {}

    with loader.driver.session(database=loader.database) as session:
        adapter = Phase5Adapter(session, pid_id)

        for trace_cat, query_entries in sorted(by_category.items()):
            logger.info("[PHASE6] Category: %s (%d queries)", trace_cat, len(query_entries))

            cat_rows = 0
            cat_errors = 0

            # Build one trace per category with all queries as steps
            builder = TraceBuilder(
                question_text=f"Phase 6 automated trace: {trace_cat}",
                category=trace_cat,
                context={"pid_id": pid_id, "trace_type": "phase6_automated"},
                pid_id=pid_id,
                graph_version="phase6",
                executed_by="run_phase6",
            )

            for qe in query_entries:
                cypher_file = PHASE5_DIR / qe["cypher_file"]
                if not cypher_file.exists():
                    logger.warning(
                        "[PHASE6]   SKIP: %s — file not found", qe["cypher_file"]
                    )
                    cat_errors += 1
                    continue

                try:
                    result = adapter.run_file(cypher_file, builder)
                    cat_rows += result["total_rows"]
                    logger.info(
                        "[PHASE6]   %-50s → %d rows",
                        qe["cypher_file"], result["total_rows"]
                    )
                except Exception as exc:
                    logger.warning(
                        "[PHASE6]   ERROR: %s — %s", qe["cypher_file"], exc
                    )
                    cat_errors += 1

            # Finalise trace
            if builder.steps:
                builder.set_summary(
                    statement=f"Executed {len(builder.steps)} queries for "
                              f"'{trace_cat}' — {cat_rows} total rows.",
                    counts={"queries": float(len(builder.steps)),
                            "rows": float(cat_rows)},
                )
                trace_dict = builder.build()

                # Write trace file
                cat_dir = TRACES_DIR / trace_cat
                cat_dir.mkdir(parents=True, exist_ok=True)
                trace_file = cat_dir / f"{trace_cat}_trace.json"
                trace_file.write_text(
                    json.dumps(trace_dict, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

                # Write category index
                _write_category_index(cat_dir, trace_cat, query_entries)

                total_traces += 1
                total_rows += cat_rows
                category_summaries[trace_cat] = {
                    "queries": len(builder.steps),
                    "rows": cat_rows,
                    "errors": cat_errors,
                }
            else:
                logger.warning(
                    "[PHASE6] No successful queries for category '%s'", trace_cat
                )

            total_errors += cat_errors

    # Step 4: Write global index
    _write_global_index(list(category_summaries.keys()), total_traces)

    # Step 5: Stamp PID status
    with loader.driver.session(database=loader.database) as s:
        s.run("""
            MATCH (pid:PID {pid_id:$pid_id})
            SET pid.status = 'PHASE6_COMPLETE'
        """, pid_id=pid_id)

    # ── Summary ────────────────────────────────────────────────────────────────
    logger.info("\n========== PHASE 6 SUMMARY | PID=%s ==========", pid_id)
    logger.info("  Total trace categories   : %d", total_traces)
    logger.info("  Total rows returned      : %d", total_rows)
    logger.info("  Total errors             : %d", total_errors)
    logger.info("  Trace output             : %s", TRACES_DIR)
    logger.info("  Category breakdown:")
    for cat, info in sorted(category_summaries.items()):
        logger.info(
            "    %-22s %3d queries  %5d rows  %d errors",
            cat, info["queries"], info["rows"], info["errors"]
        )
    logger.info("========== PHASE 6 COMPLETE | PID=%s ==========\n", pid_id)


# ── Index helpers ─────────────────────────────────────────────────────────────────

def _write_category_index(cat_dir: Path, category: str, query_entries: list) -> None:
    index = {
        "category": category,
        "traces": [
            {
                "trace_name": category,
                "file": f"{category}_trace.json",
                "produced_by": ", ".join(
                    qe["cypher_file"] for qe in query_entries
                ),
                "purpose": f"Automated Phase 6 trace for {category}",
            }
        ],
    }
    (cat_dir / "_index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_global_index(categories: list, total: int) -> None:
    index = {
        "generated_at": current_utc_time(),
        "categories": sorted(categories),
        "total_traces": total,
    }
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    (TRACES_DIR / "_global_index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── Entry point ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Phase 6 Reasoning Trace Generation."
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
            "[PHASE6] PID resolved: %s / %s / %s",
            info["plant_id"], info["skid_id"], args.pid
        )

        status = info["status"]

        if status not in {"PHASE5_COMPLETE", "PHASE6_COMPLETE",
                          "PHASE7_COMPLETE"}:
            raise RuntimeError(
                f"PID '{args.pid}' has status='{status}'. "
                "Phase 6 requires PHASE5_COMPLETE. Run Phases 0→5 first."
            )

        if status == "PHASE6_COMPLETE":
            logger.warning(
                "\n[PHASE6] WARNING: PID=%s already has status='PHASE6_COMPLETE'.\n"
                "  Re-running regenerates all trace files.\n",
                args.pid
            )
            if not args.force:
                answer = input("  Proceed with re-run? [y/N]: ").strip().lower()
                if answer != "y":
                    logger.info("[PHASE6] Aborted. No changes made.")
                    return
            clear_phase6_data(loader, args.pid)

        run_phase6(args.pid, loader)

    finally:
        loader.close()
        logger.info("[INFO] Neo4j connection closed.")


if __name__ == "__main__":
    main()
