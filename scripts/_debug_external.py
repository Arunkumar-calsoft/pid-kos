"""Diagnose external interfaces + inlet connectivity routing."""
import yaml, logging
logging.disable(logging.CRITICAL)
from agent.cli import build_agent
from agent.intent_parser import IntentParser

agent, loader, _ = build_agent()
parser = IntentParser()

questions = [
    "Show all inlet/outlet interfaces",
    "What is connected to inlet/outlet13",   # PID_2 inlet
]

for q in questions:
    intent = parser.parse(q, pid_id="PID_2")
    print(f"\nQ: {q}")
    print(f"  intent_type={intent['intent_type']}  slots={intent['slots']}")
    try:
        r = agent.answer(q, pid_id="PID_2")
        print(f"  strategy={r['strategy']}  query_id={r['query']['id']}  rows={len(r['records'])}")
        if r["records"]:
            print(f"  sample: {r['records'][0]}")
    except Exception as e:
        print(f"  ERROR: {e}")
