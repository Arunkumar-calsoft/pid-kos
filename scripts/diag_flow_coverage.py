"""
Diagnose unresolved LPS to assess flow coverage improvement potential.
"""
import sys, yaml
import io
sys.path.insert(0, ".")
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")
from neo4j import GraphDatabase

cfg = yaml.safe_load(open("config/neo4j.yaml").read())["neo4j"]
driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))
db = cfg.get("database", "chatbot")

with driver.session(database=db) as s:
    _pids = [r["pid_id"] for r in s.run("MATCH (p:PID) RETURN p.pid_id AS pid_id ORDER BY p.pid_id").data()]
    for pid in _pids:
        print(f"\n{'='*60}")
        print(f"PID: {pid}")
        print("="*60)

        # UNKNOWN LPS: any adjacent resolved neighbours?
        print("\n--- UNKNOWN LPS (adjacency check) ---")
        rows = s.run("""
            MATCH (lps:LogicalPipeSegment {pid_id:$p, flow_state:'UNKNOWN'})
            OPTIONAL MATCH (lps)-[:ADJACENT_VIA_NODES]-(adj:LogicalPipeSegment {pid_id:$p})
            WITH lps, collect(adj.flow_state) AS adj_states, collect(adj.id) AS adj_ids,
                 collect(adj.flow_direction) AS adj_dirs
            RETURN lps.id AS id, lps.phase4_hint AS hint, lps.seed_confidence AS sc,
                   adj_states, adj_ids, adj_dirs
        """, p=pid).data()
        for r in rows:
            print(f"  LPS={r['id']}  hint={r['hint']}  seed_conf={r['sc']}")
            for aid, astate, adir in zip(r["adj_ids"], r["adj_states"], r["adj_dirs"]):
                print(f"    adjacent: {aid}  state={astate}  dir={adir}")

        # BLOCKED LPS: why blocked
        print("\n--- BLOCKED LPS (blocking reason) ---")
        rows2 = s.run("""
            MATCH (lps:LogicalPipeSegment {pid_id:$p, flow_state:'BLOCKED'})
            RETURN lps.id AS id, lps.phase4_hint AS hint,
                   lps.phase4_resolution_rule AS rule,
                   lps.flow_source AS src
        """, p=pid).data()
        for r in rows2:
            print(f"  LPS={r['id']}  hint={r['hint']}  rule={r['rule']}  src={r['src']}")

        # SEEDED_UNKNOWN LPS: vote breakdown
        print("\n--- SEEDED_UNKNOWN LPS (vote breakdown) ---")
        rows3 = s.run("""
            MATCH (lps:LogicalPipeSegment {pid_id:$p, flow_state:'SEEDED_UNKNOWN'})
            OPTIONAL MATCH (e:Evidence {pid_id:$p})-[:ABOUT]->(lps)
            WITH lps, e
            ORDER BY e.confidence DESC
            WITH lps, collect(e.observed_direction + ':' + toString(round(e.confidence*100)/100)) AS votes
            RETURN lps.id AS id, lps.phase4_hint AS hint, votes,
                   lps.seed_confidence AS sc
        """, p=pid).data()
        for r in rows3:
            print(f"  LPS={r['id']}  hint={r['hint']}  seed_conf={r['sc']}  votes={r['votes']}")

        # Check if any UNKNOWN/SEEDED_UNKNOWN are actually adjacent to resolved LPS
        # (i.e. BFS might have failed to reach them)
        print("\n--- Potentially reachable UNKNOWN (adj to SEEDED/PROPAGATED) ---")
        rows4 = s.run("""
            MATCH (lps:LogicalPipeSegment {pid_id:$p})
            WHERE lps.flow_state IN ['UNKNOWN','SEEDED_UNKNOWN']
            MATCH (lps)-[:ADJACENT_VIA_NODES]-(adj:LogicalPipeSegment {pid_id:$p})
            WHERE adj.flow_state IN ['SEEDED','PROPAGATED']
            RETURN lps.id AS id, lps.flow_state AS state,
                   adj.id AS adj_id, adj.flow_direction AS adj_dir,
                   adj.flow_confidence AS adj_conf
        """, p=pid).data()
        if not rows4:
            print("  None - all UNKNOWN/SEEDED_UNKNOWN are truly isolated from resolved LPS.")
        else:
            for r in rows4:
                print(f"  LPS={r['id']} ({r['state']}) adj to {r['adj_id']} "
                      f"[{r['adj_dir']} conf={r['adj_conf']:.3f}]")

        # Summary stats
        print("\n--- Coverage Summary ---")
        r5 = s.run("""
            MATCH (lps:LogicalPipeSegment {pid_id:$p})
            RETURN lps.flow_state AS fs, count(*) AS n ORDER BY n DESC
        """, p=pid).data()
        total = sum(x["n"] for x in r5)
        resolved = sum(x["n"] for x in r5 if x["fs"] in ("SEEDED","PROPAGATED"))
        print(f"  Total LPS: {total}  Resolved: {resolved} ({100*resolved//total}%)")
        for x in r5:
            print(f"    {x['fs']:20s}: {x['n']}")

driver.close()
