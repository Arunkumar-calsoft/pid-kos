"""Smoke test — verify tier routing (Template → Registry → LLM → Schema)."""
import logging
logging.disable(logging.CRITICAL)   # suppress noisy LLM rate-limit warnings

from agent.cli import build_agent

agent, loader, llm_client = build_agent()
pid_id = "PID_0"
print(f"Registry: {len(agent.registry.queries)} queries\n")

tests = [
    ("How many valves?",                            "registry_file"),
    ("Show all dangling ends",                      "registry_file"),
    ("What is connected to tank67?",                None),  # LLM or schema
    ("Are there any engineering rule violations?",   "registry_file"),
    ("Show flow direction",                         "registry_file"),
]

passed = 0
for i, (question, expected_strategy) in enumerate(tests, 1):
    try:
        r = agent.answer(question, pid_id=pid_id)
        strategy = r["strategy"]
        qid = r["query"]["id"]
        n = len(r["records"])
        ok = (expected_strategy is None) or (strategy == expected_strategy)
        tag = "OK" if ok else "FAIL"
        line = "[%s] Test %d: %s" % (tag, i, question)
        detail = "       strategy=%-20s query=%-40s rows=%d" % (strategy, qid, n)
        print(line)
        print(detail)
        if ok:
            passed += 1
        else:
            print("       EXPECTED strategy=%s" % expected_strategy)
    except Exception as exc:
        print("[ERR] Test %d: %s" % (i, question))
        print("       %s: %s" % (type(exc).__name__, str(exc)[:120]))
    print()

print(f"{passed}/{len(tests)} tests passed")
