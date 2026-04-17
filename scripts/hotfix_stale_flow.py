"""Hotfix: remove stale flow_direction='UNKNOWN' string from UNKNOWN/BLOCKED/SEEDED_UNKNOWN LPS."""
import sys, yaml
sys.path.insert(0, ".")
from neo4j import GraphDatabase

cfg = yaml.safe_load(open("config/neo4j.yaml").read())["neo4j"]
driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))
db = cfg.get("database", "chatbot")

with driver.session(database=db) as s:
    result = s.run(
        "MATCH (lps:LogicalPipeSegment) "
        "WHERE lps.flow_state IN ['UNKNOWN', 'BLOCKED', 'SEEDED_UNKNOWN'] "
        "AND lps.flow_direction IS NOT NULL "
        "REMOVE lps.flow_direction "
        "RETURN count(lps) AS fixed"
    ).single()
    assert result is not None
    print(f"Fixed {result['fixed']} LPS nodes (removed stale flow_direction string)")

    # Also patch existing phase3_freq_summary Evidence nodes with observed_direction
    result2 = s.run(
        "MATCH (e:Evidence {source: 'phase3_freq_summary'}) "
        "WHERE e.observed_direction IS NULL AND e.direction IS NOT NULL "
        "SET e.observed_direction = e.direction "
        "RETURN count(e) AS fixed"
    ).single()
    assert result2 is not None
    print(f"Fixed {result2['fixed']} phase3_freq_summary Evidence nodes (added observed_direction)")

driver.close()
print("Done.")
