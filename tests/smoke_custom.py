"""
Smoke test — customizable queries that should bypass Phase 5 registry
and route through LLM (Tier 3) or SchemaGenerator (Tier 4).

Customizable = questions with entity tags, node IDs, numeric thresholds,
or compound filters that Phase 5 pre-built .cypher files cannot handle.
"""
import logging
import time

# Suppress noisy LLM rate-limit warnings — we only care about routing
logging.basicConfig(level=logging.WARNING)
for name in ("groq", "httpx", "httpcore"):
    logging.getLogger(name).setLevel(logging.ERROR)

from agent.cli import build_agent
from agent.intent_parser import IntentParser

agent, loader, _ = build_agent()
pid = "PID_0"
parser = IntentParser()

# ──────────────────────────────────────────────────────────────────────
# Test matrix — each entry: (question, expected_NOT_strategy, description)
# expected_NOT_strategy = strategy that SHOULD NOT be used
# None = any strategy is fine (just verify no crash)
# ──────────────────────────────────────────────────────────────────────
TESTS = [
    # ── Category 1: Node ID references (should skip Phase 5) ──
    ("What is connected to tank67?",         "registry_file", "node ID ref: tank67"),
    ("Show neighbours of valve12",           "registry_file", "node ID ref: valve12"),
    ("What type is connector5?",             "registry_file", "node ID ref: connector5"),

    # ── Category 2: Equipment tags (TAG_RE: XX-XXX-NNN) ──
    ("Show details for FV-001",              "registry_file", "equipment tag: FV-001"),
    ("What is connected to PSV-A-123?",      "registry_file", "equipment tag: PSV-A-123"),

    # ── Category 3: Numeric thresholds ──
    ("Show valves with degree greater than 5", None,           "numeric threshold: degree>5"),
    ("List nodes with more than 10 connections", None,         "numeric threshold: >10 conn"),

    # ── Category 4: Directional / path queries with specific nodes ──
    ("What is downstream of tank67?",        "registry_file", "downstream from node ID"),
    ("Show upstream equipment from valve12",  "registry_file", "upstream from node ID"),
    ("Find path between tank67 and valve12",  "registry_file", "path between node IDs"),

    # ── Category 5: Fixed queries (SHOULD use registry_file) ──
    ("How many valves?",                     None,            "fixed: valve count"),
    ("Show flow direction",                  None,            "fixed: flow direction"),
    ("Are there any engineering rule violations?", None,      "fixed: violations"),

    # ── Category 6: Mixed — entity + quality context ──
    ("Are there any orphaned instruments?",   None,           "quality + instruments"),
    ("Show dangling valve nodes",             None,           "quality + valves"),
]

print("=" * 80)
print("CUSTOMIZABLE QUERY ROUTING TEST")
print("=" * 80)
print()

passed = 0
failed = 0
errors = 0

for i, (question, bad_strategy, desc) in enumerate(TESTS, 1):
    # First check intent classification
    intent = parser.parse(question, pid_id=pid)
    intent_type = intent["intent_type"]
    tag = intent.get("slots", {}).get("tag")
    kw = intent.get("keywords", [])

    t0 = time.time()
    try:
        r = agent.answer(question, pid_id=pid)
        dt = time.time() - t0
        strategy = r["strategy"]
        qid = r["query"]["id"]
        n = len(r["records"])

        if bad_strategy and strategy == bad_strategy:
            status = "FAIL"
            failed += 1
            extra = " *** SHOULD NOT be %s ***" % bad_strategy
        else:
            status = "OK"
            passed += 1
            extra = ""

        print("[%s] %2d. %-45s" % (status, i, question))
        print("       desc=%-35s intent=%-25s" % (desc, intent_type))
        print("       strategy=%-20s query=%-40s rows=%d (%.1fs)%s" % (
            strategy, qid, n, dt, extra))
        if tag:
            print("       tag=%s" % tag)

    except BaseException as exc:
        dt = time.time() - t0
        errors += 1
        print("[ERR] %2d. %-45s" % (i, question))
        print("       desc=%-35s intent=%-25s" % (desc, intent_type))
        print("       %s: %s (%.1fs)" % (type(exc).__name__, str(exc)[:120], dt))

    print()

print("=" * 80)
print("RESULTS: %d passed, %d failed, %d errors / %d total" % (
    passed, failed, errors, len(TESTS)))
print("=" * 80)
