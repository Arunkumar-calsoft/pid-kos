import yaml
from neo4j import GraphDatabase

cfg = yaml.safe_load(open("config/neo4j.yaml"))["neo4j"]
driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))
with driver.session(database=cfg["database"]) as s:
    for pid in ["PID_0", "PID_2"]:
        fe_total = s.run(
            "MATCH (a:Arrow {pid_id: $p})-[r:FLOW_EVIDENCE]->() RETURN count(r) AS c", p=pid
        ).single()["c"]
        fe_pix = s.run(
            "MATCH (a:Arrow {pid_id: $p})-[r:FLOW_EVIDENCE]->() WHERE r.pixel_direction IS NOT NULL RETURN count(r) AS c", p=pid
        ).single()["c"]
        ev_pix = s.run(
            "MATCH (e:Evidence {pid_id: $p}) WHERE e.pixel_direction IS NOT NULL RETURN count(e) AS c", p=pid
        ).single()["c"]
        ev_total = s.run(
            "MATCH (e:Evidence {pid_id: $p, source: 'phase2_flow_evidence'}) RETURN count(e) AS c", p=pid
        ).single()["c"]
        ev_boundary = s.run(
            "MATCH (e:Evidence {pid_id: $p, source: 'phase3_boundary_semantics'}) RETURN count(e) AS c", p=pid
        ).single()["c"]
        print(f"{pid}: FLOW_EVIDENCE pixel_direction={fe_pix}/{fe_total} | Evidence pixel_direction={ev_pix}/{ev_total} | boundary_semantics={ev_boundary}")
driver.close()
