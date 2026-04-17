"""Quick intent diagnosis — run once then delete."""
from agent.intent_parser import IntentParser
from agent.query_registry import load_registry
from agent.logical_plan_builder import LogicalPlanBuilder, AmbiguityError

p = IntentParser()
registry = load_registry()
lpb = LogicalPlanBuilder(registry)

tests = [
    "Show all HIGH-severity annotations.",
    "Which pumps are missing a check valve?",
    "Show all high severity violations.",
    "Which pipe lines have low confidence?",
    "show all symbols",
    "show all instruments",
    "show all valves",
    "list all equipment",
    "how many tanks",
    "downstream of tank70",
    "show all components",
    "show all crossings",
    "show all connectors",
    "list all pipe segments",
    "what are the flow directions",
    "are there orphaned nodes",
    "show drawing issues",
    "which valves are in the wrong position",
    "show all annotation requests",
    "what is the flow coverage",
    "show me all arrows",
    "show upstream of tank4",
]

print(f"{'INTENT':35s} {'QUERY_ID':60s} | QUESTION")
print("-" * 160)
for q in tests:
    intent = p.parse(q)
    it = intent["intent_type"]
    try:
        qe = lpb.build(intent)
        qid = qe["id"]
    except AmbiguityError as e:
        qid = f"AMBIGUOUS ({len(e.candidates)} candidates)"
    except RuntimeError as e:
        qid = f"NO_MATCH (schema_gen)"
    print(f"{it:35s} {qid:60s} | {q}")
