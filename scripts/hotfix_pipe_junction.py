"""
Hotfix: remove stale pipe_junction annotations on arrow/crossing/connector/background nodes.
These were created before pattern_detection.py was fixed to exclude those label types.
"""
import sys, yaml
sys.path.insert(0, ".")
from neo4j import GraphDatabase

cfg = yaml.safe_load(open("config/neo4j.yaml").read())["neo4j"]
driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))
db = cfg.get("database", "chatbot")

EXCLUDE_LABELS = ["arrow", "crossing", "connector", "background"]

with driver.session(database=db) as s:
    r = s.run(
        "MATCH (a:Annotation {type:'pipe_junction'})-[:ANNOTATES]->(n:Node) "
        "WHERE n.label IN $labels "
        "RETURN count(a) AS cnt",
        labels=EXCLUDE_LABELS
    ).single()
    assert r is not None
    print(f"Stale pipe_junction annotations to remove: {r['cnt']}")

    r2 = s.run(
        "MATCH (a:Annotation {type:'pipe_junction'})-[:ANNOTATES]->(n:Node) "
        "WHERE n.label IN $labels "
        "DETACH DELETE a "
        "RETURN count(*) AS deleted",
        labels=EXCLUDE_LABELS
    ).single()
    assert r2 is not None
    print(f"Deleted: {r2['deleted']} annotations")

driver.close()
print("Done.")
