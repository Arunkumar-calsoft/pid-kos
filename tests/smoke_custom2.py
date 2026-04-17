"""Compact custom query test — writes results to stdout without LLM warnings."""
import logging, time, sys
logging.disable(logging.CRITICAL)
from agent.cli import build_agent
from agent.intent_parser import IntentParser

agent, loader, _ = build_agent()
pid = "PID_0"
parser = IntentParser()

TESTS = [
    ("What is connected to tank67?",           "registry_file", "node ID: tank67"),
    ("Show neighbours of valve12",             "registry_file", "node ID: valve12"),
    ("What type is connector5?",               "registry_file", "node ID: connector5"),
    ("Show details for FV-001",                "registry_file", "tag: FV-001"),
    ("What is connected to PSV-A-123?",        "registry_file", "tag: PSV-A-123"),
    ("Show valves with degree greater than 5", None,            "numeric threshold"),
    ("List nodes with more than 10 connections", None,          "numeric threshold"),
    ("What is downstream of tank67?",          "registry_file", "downstream+nodeID"),
    ("Show upstream equipment from valve12",   "registry_file", "upstream+nodeID"),
    ("Find path between tank67 and valve12",   "registry_file", "path between IDs"),
    ("How many valves?",                       None,            "fixed: valve count"),
    ("Show flow direction",                    None,            "fixed: flow"),
    ("Are there any violations?",              None,            "fixed: violations"),
    ("Are there any orphaned instruments?",    None,            "quality+instruments"),
    ("Show dangling valve nodes",              None,            "quality+valves"),
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
            print("[FAIL] %2d %-44s s=%-18s q=%-42s rows=%d it=%s tag=%s (%.1fs) ***BAD***" % (i, q, s, qid, n, it, tag, dt))
        else:
            ok += 1
            print("[ OK ] %2d %-44s s=%-18s q=%-42s rows=%d it=%s tag=%s (%.1fs)" % (i, q, s, qid, n, it, tag, dt))
    except BaseException as e:
        err += 1
        dt = time.time() - t0
        print("[ERR ] %2d %-44s %s: %s (%.1fs)" % (i, q, type(e).__name__, str(e)[:100], dt))
    sys.stdout.flush()

print("\n%d OK, %d FAIL, %d ERR / %d total" % (ok, fail, err, len(TESTS)))
