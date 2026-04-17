"""Engineering validation customizable query tests.

Covers upstream/downstream, engineering correctness, flow direction,
connectivity with entity references, drawing consistency, isolation,
redundancy, and boundary checks — all with entity-specific filters
(node IDs, tags, keywords) that must NOT hit registry_file as-is.
"""
import logging, time, sys
logging.disable(logging.CRITICAL)
from agent.cli import build_agent
from agent.intent_parser import IntentParser

agent, loader, _ = build_agent()
pid = "PID_0"
parser = IntentParser()

# Format: (query, bad_strategy_or_None, description)
# bad=None means ANY strategy is acceptable.
# bad="registry_file" means the query MUST NOT be answered by plain registry
# (it needs entity-specific Cypher from LLM or SchemaGenerator).
TESTS = [
    # ── Upstream / Downstream (node-specific) ─────────────────────────────
    ("What is downstream of tank67?",                    "registry_file", "downstream + nodeID"),
    ("Show upstream equipment from valve12",             "registry_file", "upstream + nodeID"),
    ("What is upstream of connector5?",                  "registry_file", "upstream + nodeID"),

    # ── Connectivity + entity reference ───────────────────────────────────
    ("What is connected to tank67?",                     "registry_file", "connectivity + nodeID"),
    ("Show neighbours of valve12",                       "registry_file", "neighbours + nodeID"),
    ("How many connections does tank67 have?",           "registry_file", "conn count + nodeID"),

    # ── Path queries (two node IDs) ───────────────────────────────────────
    ("Find path between tank67 and valve12",             "registry_file", "path between 2 IDs"),

    # ── Engineering correctness + entity filter ───────────────────────────
    ("Are there tanks without instruments?",             None,            "eng correctness: instr coverage"),
    ("Which tanks have no isolation valves?",            None,            "eng correctness: valve isolation"),
    ("Show branching valves with bypass potential",      None,            "eng correctness: bypass"),
    ("Check boundary integrity of inlet/outlet nodes",  None,            "eng correctness: boundary"),
    ("Show engineering correctness summary",             None,            "eng correctness: default summary"),

    # ── Flow direction + entity filter ────────────────────────────────────
    ("Show low confidence flow segments",                None,            "flow dir: low confidence"),
    ("Which segments have unknown flow direction?",      None,            "flow dir: unknown/missing"),
    ("Show flow direction summary",                      None,            "flow dir: default"),

    # ── Flow coverage ─────────────────────────────────────────────────────
    ("What is the flow coverage?",                       None,            "flow coverage: summary"),
    ("Show unresolved flow gaps",                        None,            "flow coverage: gaps"),

    # ── Drawing consistency + quality ─────────────────────────────────────
    ("Show dangling end nodes",                          None,            "quality: dangling ends"),
    ("Are there any orphaned nodes?",                    None,            "quality: orphans"),
    ("Show high degree junction nodes",                  None,            "quality: junctions"),

    # ── Isolation / reachability ──────────────────────────────────────────
    ("How many connected components are there?",         None,            "isolation: components"),
    ("Which nodes are unreachable from inlet/outlet?",   None,            "isolation: unreachable"),

    # ── Redundancy / patterns ─────────────────────────────────────────────
    ("Are there any duplicate pipe segments?",           None,            "redundancy: duplicate"),
    ("Show unusual structural patterns",                 None,            "redundancy: rare patterns"),

    # ── External interfaces ───────────────────────────────────────────────
    ("Show all inlet/outlet interfaces",                 None,            "external: list"),
    ("How many external interfaces are there?",          None,            "external: count"),

    # ── Tag-based queries ─────────────────────────────────────────────────
    ("What is connected to FV-001?",                     "registry_file", "tag connectivity"),
    ("Show details for PSV-A-123",                       "registry_file", "tag details"),

    # ── Engineering violations (fixed, should work via registry) ──────────
    ("Are there any engineering rule violations?",       None,            "violations: fixed or schema"),
    ("Show critical severity violations",                None,            "violations: critical"),
]

ok = fail = err = 0
for i, (q, bad, desc) in enumerate(TESTS, 1):
    intent = parser.parse(q, pid_id=pid)
    t0 = time.time()
    try:
        r = agent.answer(q, pid_id=pid)
        dt = time.time() - t0
        s = r["strategy"]
        qid = r["query"]["id"]
        n = len(r["records"])
        tag = intent.get("slots", {}).get("tag", "")
        it = intent["intent_type"]
        if bad and s == bad:
            fail += 1
            print("[FAIL] %2d %-52s s=%-18s rows=%-4d it=%-26s tag=%-12s (%.1fs) ***BAD: got %s***" % (
                i, q, s, n, it, tag, dt, bad))
        else:
            ok += 1
            print("[ OK ] %2d %-52s s=%-18s rows=%-4d it=%-26s tag=%-12s (%.1fs)" % (
                i, q, s, n, it, tag, dt))
    except BaseException as e:
        err += 1
        dt = time.time() - t0
        print("[ERR ] %2d %-52s %s: %s (%.1fs)" % (i, q, type(e).__name__, str(e)[:120], dt))
    sys.stdout.flush()

print("\n%d OK, %d FAIL, %d ERR / %d total" % (ok, fail, err, len(TESTS)))
