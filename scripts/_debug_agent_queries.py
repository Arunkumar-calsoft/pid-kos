"""
Quick diagnostic: find what query "Show all pipe segments" hits,
and which registry queries return bad row counts or have Cypher issues.
"""
import yaml, logging
logging.disable(logging.CRITICAL)

from agent.cli import build_agent
from agent.intent_parser import IntentParser
from neo4j import GraphDatabase

agent, loader, _ = build_agent()
parser = IntentParser()

cfg = yaml.safe_load(open("config/neo4j.yaml"))["neo4j"]
driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))

with driver.session(database=cfg["database"]) as s:
    # 1. What query does "Show all pipe segments" resolve to?
    pid = "PID_0"
    intent = parser.parse("Show all pipe segments", pid_id=pid)
    print("=== 'Show all pipe segments' intent ===")
    print(intent)

    # 2. Try running it directly to get the real error
    print("\n=== Running agent for 'Show all pipe segments' ===")
    try:
        r = agent.answer("Show all pipe segments", pid_id=pid)
        print(f"strategy={r['strategy']}  rows={len(r['records'])}")
        if r['records']:
            print("Sample:", r['records'][0])
    except Exception as e:
        print(f"ERROR: {e}")
        # Try to get the query ID
        from agent.query_registry import load_registry
        from pathlib import Path
        reg = load_registry()
        # find the matching entry
        for entry in reg.queries:
            qid = entry.get("id", "")
            if "pipe" in qid.lower() or "segment" in qid.lower() or "line" in qid.lower():
                print(f"  candidate query: {qid}")

    # 3. Check external interfaces - why 0 rows?
    print("\n=== External interfaces direct query ===")
    rows = s.run(
        "MATCH (n:Node {pid_id: 'PID_0'}) WHERE n.label = 'inlet/outlet' "
        "RETURN n.id, n.label, n.structural_type LIMIT 5"
    ).data()
    print(f"inlet/outlet nodes: {len(rows)}")
    for r in rows[:3]:
        print(r)

    # Try with CONTAINS
    rows2 = s.run(
        "MATCH (p:PID {pid_id:'PID_0'})-[:CONTAINS]->(n:Node) WHERE n.label = 'inlet/outlet' "
        "RETURN count(n) AS c"
    ).data()
    print(f"via CONTAINS: {rows2}")

    # 4. What does 'count valves' actually return?
    print("\n=== Count valves query ===")
    rows3 = s.run(
        "MATCH (p:PID {pid_id:'PID_0'})-[:CONTAINS]->(n:Node) "
        "WHERE n.structural_type = 'SYMBOL' AND n.label = 'valve' "
        "RETURN count(n) AS c"
    ).data()
    print(f"valves via CONTAINS: {rows3}")

    rows4 = s.run(
        "MATCH (n:Node {pid_id:'PID_0', label:'valve'}) RETURN count(n) AS c"
    ).data()
    print(f"valves without CONTAINS: {rows4}")

driver.close()
