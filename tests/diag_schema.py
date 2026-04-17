"""Quick schema diagnostic — what's in the graph."""
from neo4j import GraphDatabase
d = GraphDatabase.driver("neo4j://localhost:7687", auth=("neo4j","awesomepassword.0"))
with d.session(database="chatbot") as s:
    print("=== NODE LABELS ===")
    for r in s.run("MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC"):
        print(f"  {r['label']}: {r['cnt']}")

    print("\n=== RELATIONSHIP TYPES ===")
    for r in s.run("MATCH ()-[r]->() RETURN type(r) AS rel, count(r) AS cnt ORDER BY cnt DESC"):
        print(f"  {r['rel']}: {r['cnt']}")

    print("\n=== NODE.label VALUES ===")
    for r in s.run("MATCH (n:Node) RETURN n.label AS lbl, count(n) AS cnt ORDER BY cnt DESC"):
        print(f"  {r['lbl']}: {r['cnt']}")

    print("\n=== FUNCTIONAL LABELS ===")
    for r in s.run("MATCH (n:Node) WHERE n.functional_label IS NOT NULL RETURN n.functional_label AS fl, count(n) AS cnt ORDER BY cnt DESC"):
        print(f"  {r['fl']}: {r['cnt']}")

    print("\n=== ANNOTATION TYPES ===")
    for r in s.run("MATCH (a:Annotation) RETURN a.type AS t, count(a) AS cnt ORDER BY cnt DESC LIMIT 30"):
        print(f"  {r['t']}: {r['cnt']}")

    print("\n=== ENGINEERING RULE VIOLATIONS ===")
    rows = list(s.run(
        "MATCH (a:Annotation) WHERE a.type = 'engineering_rule_violation' "
        "RETURN a.pattern_type AS rule, a.severity AS sev, count(a) AS cnt ORDER BY cnt DESC"
    ))
    if not rows: print("  (none)")
    for r in rows: print(f"  {r['rule']} [{r['sev']}]: {r['cnt']}")

    print("\n=== CHECK VALVE / REVERSE FLOW PATTERNS ===")
    # Nodes with 'check' in label or inferred label
    rows = list(s.run(
        "MATCH (n:Node) WHERE n.label CONTAINS 'check' OR n.original_label CONTAINS 'check' "
        "OR n.functional_label CONTAINS 'check' RETURN n.id, n.label, n.functional_label, n.original_label LIMIT 10"
    ))
    if not rows: print("  No check valve nodes found by name")
    for r in rows: print(f"  {r['n.id']} label={r['n.label']} fl={r['n.functional_label']} ol={r['n.original_label']}")

    # Look for inferred_check_valve
    rows = list(s.run(
        "MATCH (n:Node) WHERE n.label_inferred = true RETURN n.id, n.label, n.original_label LIMIT 10"
    ))
    print(f"\n=== INFERRED LABELS (label_inferred=true) ===")
    if not rows: print("  (none)")
    for r in rows: print(f"  {r['n.id']} label={r['n.label']} original={r['n.original_label']}")

    # Annotations with pattern_type containing check/reverse/relief/safety
    print("\n=== SAFETY-RELATED ANNOTATION PATTERNS ===")
    rows = list(s.run(
        "MATCH (a:Annotation) WHERE a.pattern_type =~ '(?i).*(check|reverse|relief|safety|bypass|dead).*' "
        "RETURN DISTINCT a.pattern_type AS pt, a.type AS t, count(a) AS cnt ORDER BY cnt DESC LIMIT 20"
    ))
    if not rows: print("  (none)")
    for r in rows: print(f"  type={r['t']} pattern={r['pt']}: {r['cnt']}")

    # LPS endpoints - how many LPS have 2 endpoints
    print("\n=== LPS ENDPOINT STATS ===")
    for r in s.run(
        "MATCH (n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment) "
        "WITH lps, count(n) AS ep_count "
        "RETURN ep_count, count(lps) AS num_lps ORDER BY ep_count"
    ):
        print(f"  {r['ep_count']} endpoints: {r['num_lps']} LPS")

d.close()
