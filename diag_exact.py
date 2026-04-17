"""Check actual scoring with the real LogicalPlanBuilder, including keyword expansion."""
from agent.intent_parser import IntentParser
from agent.query_registry import load_registry
from agent.logical_plan_builder import LogicalPlanBuilder, AmbiguityError, _stem

p = IntentParser()
registry = load_registry()
lpb = LogicalPlanBuilder(registry)

QUERIES_BY_INTENT = {v["intent"]: [] for v in registry.queries}
for v in registry.queries:
    QUERIES_BY_INTENT[v["intent"]].append(v)

def show_top(question, intent_override=None):
    intent = p.parse(question)
    if intent_override:
        intent["intent_type"] = intent_override
    it = intent["intent_type"]
    kw = set(intent["keywords"])
    stemmed_kw = {_stem(k) for k in kw}
    print(f"\n>>> '{question}'")
    print(f"    intent={it}, keywords={sorted(kw)[:8]}...")
    
    pool = [q for q in registry.queries if q["intent"] == it]
    # required filter
    pool = [q for q in pool if all(rk.lower() in kw for rk in q.get("required_keywords",[]))]
    # exclude filter
    pool = [q for q in pool if not ({k.lower() for k in q.get("exclude_keywords",[])} & kw)]
    
    # op filter
    if kw & {"how","many","count","total","quantity"}:
        op = "count"
    elif kw & {"path","between","route"}:
        op = "path"
    elif kw & {"list","show","which","what","all"}:
        op = "list"
    else:
        op = None
    if op:
        narrowed = [q for q in pool if q.get("operation") == op]
        if narrowed:
            pool = narrowed
    
    scores = []
    for q in pool:
        boost = {k.lower() for k in q.get("boost_keywords",[])}
        exact = len(boost & kw)
        stemmed_boost = {_stem(b) for b in boost}
        stem = len(stemmed_boost & stemmed_kw) - exact
        score = exact * 5 + max(stem,0) * 3
        op_cur = q.get("operation","")
        scores.append((score, op_cur, q["id"]))
    scores.sort(key=lambda x: (-x[0], x[2]))
    top = scores[0][0] if scores else 0
    print(f"    pool_size={len(pool)}, top_score={top}")
    for s,op_cur,qid in scores[:5]:
        marker = " ✓" if s == top else ""
        print(f"    {s:3d} [{op_cur:5s}] {qid[:65]}{marker}")

show_top("show all valves")
show_top("show all symbols")
show_top("Show all HIGH-severity annotations.")
show_top("show all annotation requests")
show_top("what is the flow coverage")
show_top("downstream of tank70")
show_top("Which pumps are missing a check valve?")
show_top("show drawing issues")
