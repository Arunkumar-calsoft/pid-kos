"""Deep ambiguity analysis — show scored candidates for specific queries."""
import json
from pathlib import Path

# Load registry
reg = json.loads(Path("engine/phase5_cypher/_meta/queries.json").read_text())
queries = [v for v in reg["queries"].values() if v.get("verified")]

def _stem(word: str) -> str:
    w = word.lower()
    for suffix in ("ations","ments","ness","tion","ment","ing","ies","ous","ive",
                   "ity","ed","es","ly","er","s"):
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            return w[:-len(suffix)]
    return w

def score_query(q, keywords, slots=None):
    slots = slots or {}
    boost = {k.lower() for k in q.get("boost_keywords", [])}
    kw = set(keywords)
    stemmed_kw = {_stem(k) for k in kw}
    exact_hits = len(boost & kw)
    stemmed_boost = {_stem(b) for b in boost}
    stem_hits = len(stemmed_boost & stemmed_kw) - exact_hits
    score = exact_hits * 5 + max(stem_hits, 0) * 3
    if "tag" in slots and q.get("target_entity"):
        score += 3
    return score

def diagnose(question_tokens, intent, slots=None):
    """Show top-N scored candidates for a question."""
    print(f"\n>>> tokens={question_tokens}, intent={intent}")
    pool = [q for q in queries if q["intent"] == intent]
    
    # Filter required_keywords
    kw_set = set(question_tokens)
    pool = [q for q in pool if all(
        rk.lower() in kw_set for rk in q.get("required_keywords", [])
    )]
    
    # Filter exclude
    pool = [q for q in pool if not (
        {k.lower() for k in q.get("exclude_keywords", [])} & kw_set
    )]
    
    # Detect operation
    op = None
    if kw_set & {"how","many","count","total","quantity"}:
        op = "count"
    elif kw_set & {"path","between","route"}:
        op = "path"
    elif kw_set & {"list","show","which","what","all"}:
        op = "list"
    
    if op:
        narrowed = [q for q in pool if q.get("operation") == op]
        if narrowed:
            pool = narrowed
    
    scored = [(score_query(q, kw_set, slots), q) for q in pool]
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    
    top = scored[0][0] if scored else 0
    winners = [q for s,q in scored if s == top]
    print(f"  top_score={top}, winners={len(winners)}, total_pool={len(pool)}")
    for s, q in scored[:8]:
        req = q.get("required_keywords",[])
        marker = " *** WINNER" if s == top else ""
        print(f"  score={s:3d} [{q.get('operation','?'):5s}] {q['id'][:70]}{marker}")
        if req:
            print(f"         required={req}")

# Key failing queries
diagnose(["show","all","instruments"], "instrument_attachment")
diagnose(["show","all","valves"], "valve_placement")
diagnose(["show","all","symbols"], "engineering_inventory")
diagnose(["downstream","of","tank70"], "connectivity_topology", {"tag":"tank70"})
diagnose(["show","all","high","severity","annotations"], "cross_domain")
diagnose(["show","all","high","severity","violations"], "engineering_correctness")
diagnose(["show","drawing","issues"], "drawing_consistency")
diagnose(["show","all","annotation","requests"], "annotation_requests")
diagnose(["what","is","the","flow","coverage"], "flow_coverage")
diagnose(["which","pipe","lines","have","low","confidence"], "flow_coverage")
diagnose(["show","all","components"], "engineering_inventory")
diagnose(["list","all","pipe","segments"], "line_attributes")
diagnose(["show","all","equipment","symbols"], "engineering_inventory")
diagnose(["show","all","isolated","symbols"], "isolation_reachability")
