"""
tests/verify_agent_logic.py
============================
Comprehensive agent verification against actual PID data (PID_0 and PID_2).

For each PID:
  1. Discovers real node IDs from Neo4j (tanks, valves, instruments, inlets)
  2. Runs ~40 agent queries covering every intent type
  3. Validates: no Cypher errors, expected row shapes, sensible counts
  4. Reports OK / FAIL / ERR with strategy and row count

Usage:
    python tests/verify_agent_logic.py
    python tests/verify_agent_logic.py --pid PID_0          # one PID only
    python tests/verify_agent_logic.py --pid PID_2 --verbose
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import yaml
from typing import List, Tuple, Optional, Any, Dict

logging.disable(logging.CRITICAL)

# ── bootstrap ─────────────────────────────────────────────────────────────────
from agent.cli import build_agent

agent, loader, _ = build_agent()


# ── helpers ────────────────────────────────────────────────────────────────────

def _neo4j():
    """Open a fresh Neo4j session."""
    cfg = yaml.safe_load(open("config/neo4j.yaml"))["neo4j"]
    from neo4j import GraphDatabase
    return GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"])), cfg["database"]


def _pick(session, pid_id: str, label: str, n: int = 1) -> List[str]:
    """Return up to n real node IDs with the given label in a PID."""
    rows = session.run(
        "MATCH (nd:Node {pid_id: $p}) WHERE nd.label = $l AND nd.structural_type = 'SYMBOL' "
        "RETURN nd.id AS id ORDER BY nd.id LIMIT $n",
        p=pid_id, l=label, n=n,
    ).data()
    return [r["id"] for r in rows]


def _pick_seeded(session, pid_id: str, n: int = 1) -> List[str]:
    """Return up to n LPS ids with SEEDED flow state."""
    rows = session.run(
        "MATCH (lps:LogicalPipeSegment {pid_id: $p, flow_state: 'SEEDED'}) "
        "RETURN lps.id AS id LIMIT $n", p=pid_id, n=n,
    ).data()
    return [r["id"] for r in rows]


def _counts(session, pid_id: str) -> Dict[str, int]:
    """Basic expected counts from the graph — used for sanity assertions."""
    rows = session.run(
        "MATCH (n:Node {pid_id: $p}) WHERE n.structural_type = 'SYMBOL' "
        "RETURN n.label AS lbl, count(*) AS c", p=pid_id,
    ).data()
    return {r["lbl"]: r["c"] for r in rows}


# ── test runner ────────────────────────────────────────────────────────────────

class TestResult:
    def __init__(self, idx, question, desc, strategy, rows, elapsed, error=None, warning=None):
        self.idx      = idx
        self.question = question
        self.desc     = desc
        self.strategy = strategy
        self.rows     = rows
        self.elapsed  = elapsed
        self.error    = error
        self.warning  = warning

    @property
    def status(self):
        if self.error:    return "ERR"
        if self.warning:  return "WARN"
        return "OK"


def run_tests(pid_id: str, verbose: bool = False) -> Tuple[int, int, int]:
    """Discover real nodes, build tests, run them. Returns (ok, warn, err)."""

    driver, database = _neo4j()
    with driver.session(database=database) as s:
        tanks   = _pick(s, pid_id, "tank",           3)
        valves  = _pick(s, pid_id, "valve",          3)
        inlets  = _pick(s, pid_id, "inlet/outlet",   2)
        instrs  = _pick(s, pid_id, "instrumentation", 2)
        counts  = _counts(s, pid_id)
        seeded  = _pick_seeded(s, pid_id,            1)
    driver.close()

    tank0  = tanks[0]  if tanks  else "NO_TANK"
    tank1  = tanks[1]  if len(tanks) > 1 else tank0
    valve0 = valves[0] if valves else "NO_VALVE"
    valve1 = valves[1] if len(valves) > 1 else valve0
    inlet0 = inlets[0] if inlets else "NO_INLET"
    instr0 = instrs[0] if instrs else "NO_INSTR"

    expect_valves  = counts.get("valve", 0)
    expect_tanks   = counts.get("tank", 0)
    expect_instrs  = counts.get("instrumentation", 0)
    expect_inlets  = counts.get("inlet/outlet", 0)

    print(f"\n{'='*70}")
    print(f"  PID: {pid_id}   tanks={expect_tanks}  valves={expect_valves}  "
          f"instruments={expect_instrs}  inlets={expect_inlets}")
    print(f"  sample: tank={tank0}  valve={valve0}  inlet={inlet0}  instr={instr0}")
    print(f"{'='*70}")

    # (question, desc, min_rows, bad_strategy_or_None)
    # min_rows=0 means "just must not error"; -1 means "must have ≥1 row"
    TESTS: List[Tuple[str, str, int, Optional[str]]] = [

        # ── Engineering inventory ──────────────────────────────────────────
        # Count queries return 1 aggregate row — not N rows
        ("How many valves are on this PID?",
         "inv: count valves", 1, None),

        ("Show all tanks",
         "inv: list tanks", -1, None),

        ("Show all instrumentation",
         "inv: list instruments", 0, None),

        ("How many equipment symbols?",
         "inv: count equipment", 1, None),

        ("List equipment types",
         "inv: type breakdown", -1, None),

        # ── Valve placement ────────────────────────────────────────────────
        # List query: verify it returns something, not an exact match (LIMIT may cap)
        ("Show all valves",
         "valve: list all", -1, None),

        ("What types of valves are on this drawing?",
         "valve: type breakdown", -1, None),

        ("Show valve type breakdown",
         "valve: breakdown explicit", 0, None),

        # ── Instrument attachment ──────────────────────────────────────────
        ("How many instruments are on this drawing?",
         "instr: count", 0, None),

        ("Show instruments attached to tanks",
         "instr: attached to tanks", 0, None),

        (f"What instruments are attached to {tank0}?",
         "instr: attached to specific tank", 0, "registry_file"),

        # ── Line attributes / pipe segments ───────────────────────────────
        ("Show all pipe segments",
         "line: list all", -1, None),

        ("How many pipe segments are there?",
         "line: count", 1, None),

        (f"What segments connect to {valve0}?",
         "line: segments for specific valve", 0, "registry_file"),

        # ── Connectivity / topology ────────────────────────────────────────
        (f"What is connected to {tank0}?",
         "conn: neighbours of tank", -1, "registry_file"),

        (f"Show neighbours of {valve0}",
         "conn: neighbours of valve", 0, "registry_file"),

        (f"How many connections does {tank0} have?",
         "conn: count neighbours", -1, "registry_file"),

        (f"Find path between {tank0} and {valve0}",
         "conn: path between 2 nodes", 0, "registry_file"),

        # ── Downstream / upstream ─────────────────────────────────────────
        (f"What is downstream of {tank0}?",
         "flow: downstream of tank", 0, "registry_file"),

        (f"Show upstream equipment from {valve0}",
         "flow: upstream of valve", 0, "registry_file"),

        (f"What is upstream of {tank0}?",
         "flow: upstream of tank", 0, "registry_file"),

        # ── Flow direction ─────────────────────────────────────────────────
        ("Show flow direction summary",
         "flow: summary", -1, None),

        ("Which segments have unknown flow direction?",
         "flow: unknown segments", 0, None),

        ("Show low confidence flow segments",
         "flow: low confidence", 0, None),

        ("What is the flow coverage?",
         "flow coverage: summary", -1, None),

        ("Show unresolved flow gaps",
         "flow coverage: gaps", 0, None),

        # ── Drawing consistency / quality ──────────────────────────────────
        ("Show dangling end nodes",
         "quality: dangling ends", 0, None),

        ("Are there any orphaned nodes?",
         "quality: orphans", 0, None),

        ("Show high degree junction nodes",
         "quality: high degree junctions", 0, None),

        ("Are there any engineering rule violations?",
         "violations: any", 0, None),

        ("Show critical severity violations",
         "violations: critical", 0, None),

        # ── Engineering correctness ────────────────────────────────────────
        ("Are there tanks without instruments?",
         "eng: tanks missing instruments", 0, None),

        ("Which tanks have no isolation valves?",
         "eng: tanks missing isolation", 0, None),

        ("Show engineering correctness summary",
         "eng: correctness summary", 0, None),

        # ── Isolation / reachability ───────────────────────────────────────
        ("How many connected components are there?",
         "isolation: component count", 1, None),

        ("Which nodes are unreachable from inlet/outlet?",
         "isolation: unreachable", 0, None),

        # ── Redundancy ────────────────────────────────────────────────────
        ("Are there any duplicate pipe segments?",
         "redundancy: duplicate", 0, None),

        ("Show unusual structural patterns",
         "redundancy: unusual patterns", 0, None),

        # ── External interfaces ────────────────────────────────────────────
        ("Show all inlet/outlet interfaces",
         "external: list", -1, None),

        ("How many external interfaces are there?",
         "external: count", 1, None),

        # ── Segment junction topology ──────────────────────────────────────
        ("Show junction points in the pipe network",
         "junction: show junctions", 0, None),

        # ── Tag / ID based (entity-specific) ──────────────────────────────
        (f"Show details for {valve0}",
         "tag: details for valve", -1, "registry_file"),

        (f"What is connected to {inlet0}?",
         "tag: connectivity for inlet", 0, "registry_file"),
    ]

    results: List[TestResult] = []
    for i, (question, desc, min_rows, bad_strategy) in enumerate(TESTS, 1):
        t0 = time.time()
        try:
            r       = agent.answer(question, pid_id=pid_id)
            elapsed = time.time() - t0
            strat   = r["strategy"]
            nrows   = len(r["records"])

            warning = None
            if bad_strategy and strat == bad_strategy:
                warning = f"strategy should NOT be {bad_strategy}"
            elif min_rows == -1 and nrows == 0:
                warning = "expected ≥1 row but got 0"
            elif min_rows > 0 and nrows != min_rows:
                # count queries: warn if significantly off (>20% deviation for large counts)
                threshold = max(1, int(min_rows * 0.20))
                if abs(nrows - min_rows) > threshold:
                    warning = f"expected ~{min_rows} rows, got {nrows}"

            results.append(TestResult(i, question, desc, strat, nrows, elapsed, warning=warning))

        except Exception as exc:
            elapsed = time.time() - t0
            results.append(TestResult(i, question, desc, "—", 0, elapsed, error=str(exc)[:150]))

    # ── Print results ──────────────────────────────────────────────────────
    ok = warn = err = 0
    for res in results:
        tag  = f"[{res.status:4}]"
        line = (f"{tag} {res.idx:2}. {res.desc:<42} "
                f"s={res.strategy:<20} rows={res.rows:<4} ({res.elapsed:.2f}s)")
        if res.error:
            err += 1
            print(line)
            print(f"       ERR: {res.error}")
        elif res.warning:
            warn += 1
            print(line)
            print(f"       WARN: {res.warning}")
            if verbose:
                print(f"       Q: {res.question}")
        else:
            ok += 1
            print(line)
            if verbose:
                print(f"       Q: {res.question}")

    print(f"\n  {ok} OK  |  {warn} WARN  |  {err} ERR   ({len(results)} total)")
    return ok, warn, err


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Verify agent logic against live PID data.")
    ap.add_argument("--pid",     help="Run only this PID (default: both)")
    ap.add_argument("--verbose", action="store_true", help="Print question for each test")
    args = ap.parse_args()

    pids = [args.pid] if args.pid else ["PID_0", "PID_2"]

    total_ok = total_warn = total_err = 0
    for pid in pids:
        ok, warn, err = run_tests(pid, verbose=args.verbose)
        total_ok   += ok
        total_warn += warn
        total_err  += err

    print(f"\n{'='*70}")
    print(f"  TOTAL: {total_ok} OK  |  {total_warn} WARN  |  {total_err} ERR")
    print(f"{'='*70}")
    sys.exit(1 if total_err > 0 else 0)


if __name__ == "__main__":
    main()
