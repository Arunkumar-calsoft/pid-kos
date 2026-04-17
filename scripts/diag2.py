"""Quick diagnostic for P2-3 and P4-4 bugs."""
import sys, yaml
sys.path.insert(0, ".")
from neo4j import GraphDatabase

cfg = yaml.safe_load(open("config/neo4j.yaml").read())["neo4j"]
driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))
db = cfg.get("database", "chatbot")

with driver.session(database=db) as s:
    # P2-3: What sources produce Evidence nodes missing observed_direction?
    rows = s.run(
        "MATCH (e:Evidence) WHERE e.observed_direction IS NULL "
        "RETURN e.source AS src, count(e) AS cnt ORDER BY cnt DESC"
    ).data()
    print("Evidence nodes missing observed_direction, by source:")
    for r in rows:
        print(" ", r["src"], r["cnt"])
    print()

    # Sample a few
    rows2 = s.run(
        "MATCH (e:Evidence) WHERE e.observed_direction IS NULL "
        "RETURN e.id AS id, e.source AS src, e.pid_id AS pid, "
        "coalesce(e.direction_hint,'NULL') AS hint LIMIT 10"
    ).data()
    print("Sample Evidence nodes missing observed_direction:")
    for r in rows2:
        print(" ", r)
    print()

    # P4-4: UNKNOWN/BLOCKED LPS with non-null flow_direction
    rows3 = s.run(
        "MATCH (lps:LogicalPipeSegment) "
        "WHERE lps.flow_state IN ['UNKNOWN','BLOCKED','SEEDED_UNKNOWN'] "
        "AND lps.flow_direction IS NOT NULL "
        "RETURN lps.pid_id AS pid, lps.flow_state AS fs, "
        "lps.flow_direction AS fd, count(*) AS cnt "
        "ORDER BY pid, fs"
    ).data()
    print("UNKNOWN/BLOCKED LPS with non-null flow_direction:")
    for r in rows3:
        print(" ", r)

driver.close()
print("Done.")
