"""P&ID Safety & HAZOP-style query tests.

Covers real-world P&ID engineer queries identified from industry research:
  - Check valve / reverse flow protection
  - Valve inventory by type
  - Equipment listing (pumps, inline equipment)
  - Violation sub-type and severity filtering
  - Suction strainer coverage
  - Dead-end / dead-leg detection
  - HAZOP-style queries (reverse flow, isolation)
"""
import logging, time, sys
logging.disable(logging.CRITICAL)
from agent.cli import build_agent
from agent.intent_parser import IntentParser

agent, loader, _ = build_agent()
pid = "PID_0"
parser = IntentParser()

# Format: (query, bad_strategy_or_None, description)
TESTS = [
    # ── Check valve / reverse flow protection ─────────────────────────────
    ("Show all check valves",                            None,            "check valve listing"),
    ("How many check valves are there?",                 None,            "check valve count"),
    ("Where are check valves located?",                  None,            "check valve locations"),
    ("Is there reverse flow protection?",                None,            "reverse flow protection"),
    ("Show missing check valve violations",              None,            "missing check valve violations"),

    # ── Valve type breakdown ──────────────────────────────────────────────
    ("What types of valves are on this drawing?",        None,            "valve type breakdown"),

    # ── Equipment listing by inferred type ────────────────────────────────
    ("Show all pumps",                                   None,            "pump listing"),
    ("How many pumps are there?",                        None,            "pump count"),
    ("Show all inline equipment",                        None,            "inline equipment listing"),
    ("How many inline equipment symbols?",               None,            "inline equipment count"),

    # ── Violation sub-type filtering ──────────────────────────────────────
    ("Show missing isolation valve violations",          None,            "isolation valve violations"),
    ("Show missing suction strainer violations",         None,            "suction strainer violations"),
    ("Are there any missing suction strainers?",         None,            "suction strainer check"),

    # ── Violation severity filtering ──────────────────────────────────────
    ("Show critical severity violations",                None,            "critical violations"),
    ("Show high severity violations",                    None,            "high severity violations"),

    # ── Dead-end / dead-leg detection (existing handlers) ─────────────────
    ("Show dead-end pipe segments",                      None,            "dead-end segments"),
    ("Are there any dead legs?",                         None,            "dead legs"),

    # ── HAZOP-style queries ───────────────────────────────────────────────
    ("Where can reverse flow occur?",                    None,            "HAZOP: reverse flow"),
    ("Which equipment has no check valve?",              None,            "HAZOP: missing check valve"),
    ("Which tanks have no isolation valves?",            None,            "HAZOP: missing isolation"),
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
