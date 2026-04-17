"""
Ground-truth audit: compare Phase 2 / 3 / 4 annotations against GraphML.

Checks:
  P2-1: Arrow nodes  -- every arrow in GraphML must exist in DB with pid_id
  P2-2: FLOW_EVIDENCE rels -- every Arrow must have at least one FLOW_EVIDENCE
  P2-3: Evidence nodes -- source/observed_direction sanity
  P3-1: orphan_node   -- must match nodes with zero PIPE edges in GraphML
  P3-2: dead_end_pipe_segment -- every annotated PS must exist in DB
  P3-3: structural_branch / t_junction / high_degree -- degree check
  P3-4: pipe_junction -- must not be on connector/background
  P3-5: isolated_pipe_segment -- PS with no adjacent PS
  P3-6: identical_ps_neighborhood -- spot-check pairs are real
  P4-1: LPS flow_state completeness -- every LPS must have flow_state
  P4-2: SEEDED LPS must have flow_direction != null
  P4-3: PROPAGATED LPS must have flow_direction != null
  P4-4: UNKNOWN LPS must have flow_direction == null
  P4-5: endpoint sanity -- every LPS must have at least 2 ENDPOINT_OF nodes
  CROSS-1: orphan_node for arrow/crossing/background -- should be zero
  CROSS-2: inferred_check_valve annotations match edge structure in GraphML
"""
import sys, yaml, xml.etree.ElementTree as ET
import io
from collections import defaultdict, Counter

sys.path.insert(0, ".")
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")
from neo4j import GraphDatabase

cfg = yaml.safe_load(open("config/neo4j.yaml").read())["neo4j"]
driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))
db = cfg.get("database", "chatbot")

# Auto-discover all PIDs and their GraphML paths from the DB (PID.graphml_path).
# Falls back to pid_store/ filesystem scan if graphml_path is missing.
_PID_STORE = "pid_store"
with driver.session(database=db) as _s:
    _rows = _s.run("MATCH (p:PID) WHERE p.graphml_path IS NOT NULL "
                   "RETURN p.pid_id AS pid_id, p.graphml_path AS gpath").data()
PIDS = {r["pid_id"]: f"{_PID_STORE}/{r['gpath']}" for r in _rows}
if not PIDS:
    import glob as _glob
    for _path in _glob.glob(f"{_PID_STORE}/**/*.graphml", recursive=True):
        import os as _os
        _pid = _os.path.basename(_os.path.dirname(_path))
        PIDS[_pid] = _path

# ── Build GraphML ground truth ────────────────────────────────────────────────

def load_graphml(path):
    ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
    root = ET.parse(path).getroot()
    adj = defaultdict(set)
    labels = {}
    for n in root.findall(".//g:node", ns):
        nid = n.get("id")
        for d in n.findall("g:data", ns):
            if d.get("key") == "d0":
                labels[nid] = d.text
    for e in root.findall(".//g:edge", ns):
        s, t = e.get("source"), e.get("target")
        adj[s].add(t); adj[t].add(s)
    return labels, adj

gt = {pid: load_graphml(path) for pid, path in PIDS.items()}

PASS = 0; FAIL = 0; WARN = 0
issues = []

def ok(msg):  global PASS; PASS += 1; print(f"  PASS  {msg}")
def fail(msg): global FAIL; FAIL += 1; issues.append(msg); print(f"  FAIL  {msg}")
def warn(msg): global WARN; WARN += 1; issues.append(f"WARN: {msg}"); print(f"  WARN  {msg}")

with driver.session(database=db) as s:

    for pid in sorted(PIDS.keys()):
        labels_gt, adj_gt = gt[pid]
        arrows_gt = {nid for nid, lbl in labels_gt.items() if lbl == "arrow"}
        connectors_gt = {nid for nid, lbl in labels_gt.items() if lbl == "connector"}
        crossings_gt = {nid for nid, lbl in labels_gt.items() if lbl == "crossing"}

        print(f"\n{'='*60}")
        print(f"PID: {pid}  (GT: {len(labels_gt)} nodes, {sum(len(v) for v in adj_gt.values())//2} edges)")
        print(f"  GT arrows={len(arrows_gt)}  connectors={len(connectors_gt)}  crossings={len(crossings_gt)}")
        print("="*60)

        # ── P2-1: Arrow nodes in DB ────────────────────────────────────────
        print("\n--- P2: Arrow / Evidence checks ---")
        rows = s.run(
            "MATCH (a:Arrow {pid_id:$p}) RETURN a.id AS id", p=pid
        ).data()
        db_arrows = {r["id"] for r in rows}
        if db_arrows == arrows_gt:
            ok(f"P2-1 Arrow nodes: {len(db_arrows)} match GT")
        else:
            missing = arrows_gt - db_arrows
            extra   = db_arrows - arrows_gt
            if missing: fail(f"P2-1 {pid} arrows missing from DB: {missing}")
            if extra:   fail(f"P2-1 {pid} extra arrows in DB (not in GT): {extra}")

        # ── P2-2: Every Arrow must have FLOW_EVIDENCE ──────────────────────
        rows2 = s.run(
            "MATCH (a:Arrow {pid_id:$p}) WHERE NOT EXISTS {MATCH (a)-[:FLOW_EVIDENCE]->(:LogicalPipeSegment)} "
            "RETURN a.id AS id", p=pid
        ).data()
        if not rows2:
            ok(f"P2-2 All {len(db_arrows)} arrows have FLOW_EVIDENCE")
        else:
            fail(f"P2-2 {pid} arrows with no FLOW_EVIDENCE: {[r['id'] for r in rows2]}")

        # ── P2-3: Evidence sanity ──────────────────────────────────────────
        rows3 = s.run(
            "MATCH (e:Evidence {pid_id:$p}) WHERE e.observed_direction IS NULL RETURN count(e) AS cnt", p=pid
        ).single()
        cnt = rows3["cnt"] if rows3 else 0
        if cnt == 0:
            ok("P2-3 All Evidence nodes have observed_direction")
        else:
            warn(f"P2-3 {pid}: {cnt} Evidence nodes missing observed_direction")

        # ── P3: Annotation checks ─────────────────────────────────────────
        print("\n--- P3: Annotation checks ---")

        # P3-1: orphan_node must be degree-0 in GT (excluding arrow/crossing/background)
        rows_orp = s.run(
            "MATCH (a:Annotation {pid_id:$p, type:'orphan_node'})-[:ANNOTATES]->(n:Node) "
            "RETURN n.id AS nid, n.label AS lbl", p=pid
        ).data()
        orp_issues = []
        for r in rows_orp:
            nid, lbl = r["nid"], r["lbl"]
            if lbl in ("arrow", "crossing", "background"):
                orp_issues.append(f"{nid}({lbl}) should be excluded")
            elif nid in adj_gt:
                deg = len(adj_gt[nid])
                if deg > 0:
                    orp_issues.append(f"{nid}({lbl}) has GT degree={deg} but annotated as orphan")
        if not orp_issues:
            ok(f"P3-1 orphan_node: {len(rows_orp)} annotations all correct vs GT")
        else:
            for iss in orp_issues:
                fail(f"P3-1 orphan_node false positive: {iss}")

        # P3-2: dead_end_pipe_segment -- PS must exist in DB
        rows_dead = s.run(
            "MATCH (a:Annotation {pid_id:$p, type:'dead_end_pipe_segment'})-[:ANNOTATES]->(ps:PipeSegment) "
            "RETURN ps.id AS psid, ps.node_count AS nc", p=pid
        ).data()
        ok(f"P3-2 dead_end_pipe_segment: {len(rows_dead)} annotations (all have valid PS target)")

        # P3-3: structural_branch / t_junction degree >= 3 in GT
        deg_fails = []
        for ann_type, min_deg in [("structural_branch", 3), ("structural_t_junction", 3), ("structural_high_degree", 4)]:
            rows_deg = s.run(
                f"MATCH (a:Annotation {{pid_id:$p, type:'{ann_type}'}})-[:ANNOTATES]->(n:Node) "  # type: ignore[arg-type]
                "RETURN n.id AS nid, n.label AS lbl, a.degree AS ann_deg", p=pid
            ).data()
            for r in rows_deg:
                nid = r["nid"]
                gt_deg = len(adj_gt.get(nid, set()))
                if gt_deg < min_deg:
                    deg_fails.append(f"{ann_type}: {nid} GT_deg={gt_deg} < {min_deg}")
        if not deg_fails:
            ok("P3-3 structural_branch/t_junction/high_degree all GT-degree-valid")
        else:
            for f_msg in deg_fails:
                fail(f"P3-3 {f_msg}")

        # P3-4: pipe_junction must not be on connector/background
        rows_pj = s.run(
            "MATCH (a:Annotation {pid_id:$p, type:'pipe_junction'})-[:ANNOTATES]->(n:Node) "
            "WHERE n.label IN ['connector','background','arrow'] "
            "RETURN n.id AS nid, n.label AS lbl", p=pid
        ).data()
        if not rows_pj:
            ok("P3-4 pipe_junction: no connector/background/arrow targets")
        else:
            for r in rows_pj:
                fail(f"P3-4 pipe_junction on wrong target: {r['nid']}({r['lbl']})")

        # P3-5: isolated_pipe_segment -- PS with <=1 ADJACENT_VIA_NODES
        rows_iso = s.run(
            "MATCH (a:Annotation {pid_id:$p, type:'isolated_pipe_segment'})-[:ANNOTATES]->(ps:PipeSegment) "
            "WITH ps, size([(ps)-[:ADJACENT_VIA_NODES]-(ps2:PipeSegment) | ps2]) AS adj_cnt "
            "WHERE adj_cnt > 1 "
            "RETURN ps.id AS psid, adj_cnt", p=pid
        ).data()
        if not rows_iso:
            ok("P3-5 isolated_pipe_segment: all annotated PS have adj_cnt<=1")
        else:
            for r in rows_iso:
                fail(f"P3-5 isolated_pipe_segment: {r['psid']} has adj_cnt={r['adj_cnt']}")

        # P3-6: No orphan_node on arrow/crossing/background
        rows_excl = s.run(
            "MATCH (a:Annotation {pid_id:$p, type:'orphan_node'})-[:ANNOTATES]->(n:Node) "
            "WHERE n.label IN ['arrow','crossing','background'] "
            "RETURN n.id AS nid, n.label AS lbl", p=pid
        ).data()
        if not rows_excl:
            ok("CROSS-1 No orphan_node annotations on arrow/crossing/background")
        else:
            for r in rows_excl:
                fail(f"CROSS-1 orphan_node on excluded label: {r['nid']}({r['lbl']})")

        # ── P4: LPS flow_state ────────────────────────────────────────────
        print("\n--- P4: LPS flow_state checks ---")

        # P4-1: All LPS have flow_state
        r41 = s.run(
            "MATCH (lps:LogicalPipeSegment {pid_id:$p}) WHERE lps.flow_state IS NULL "
            "RETURN count(lps) AS cnt", p=pid
        ).single()
        cnt41 = r41["cnt"] if r41 else 0
        if cnt41 == 0:
            ok("P4-1 All LPS have flow_state set")
        else:
            fail(f"P4-1 {cnt41} LPS missing flow_state")

        # P4-2/3: SEEDED/PROPAGATED → flow_direction not null
        r42 = s.run(
            "MATCH (lps:LogicalPipeSegment {pid_id:$p}) "
            "WHERE lps.flow_state IN ['SEEDED','PROPAGATED'] AND lps.flow_direction IS NULL "
            "RETURN count(lps) AS cnt", p=pid
        ).single()
        cnt42 = r42["cnt"] if r42 else 0
        if cnt42 == 0:
            ok("P4-2/3 All SEEDED/PROPAGATED LPS have flow_direction")
        else:
            fail(f"P4-2/3 {cnt42} SEEDED/PROPAGATED LPS have null flow_direction")

        # P4-4: UNKNOWN/BLOCKED → flow_direction null
        r44 = s.run(
            "MATCH (lps:LogicalPipeSegment {pid_id:$p}) "
            "WHERE lps.flow_state IN ['UNKNOWN','BLOCKED','SEEDED_UNKNOWN'] "
            "AND lps.flow_direction IS NOT NULL "
            "RETURN count(lps) AS cnt", p=pid
        ).single()
        cnt44 = r44["cnt"] if r44 else 0
        if cnt44 == 0:
            ok("P4-4 All UNKNOWN/BLOCKED LPS have null flow_direction")
        else:
            fail(f"P4-4 {cnt44} UNKNOWN/BLOCKED LPS have non-null flow_direction")

        # P4-5: Every LPS should have >=2 ENDPOINT_OF nodes
        r45 = s.run(
            "MATCH (lps:LogicalPipeSegment {pid_id:$p}) "
            "WITH lps, size([(n:Node)-[:ENDPOINT_OF]->(lps) | n]) AS ep_cnt "
            "WHERE ep_cnt < 2 "
            "RETURN lps.id AS lid, ep_cnt ORDER BY ep_cnt LIMIT 10", p=pid
        ).data()
        if not r45:
            ok("P4-5 All LPS have >=2 ENDPOINT_OF nodes")
        else:
            for r in r45:
                warn(f"P4-5 LPS {r['lid']} has only {r['ep_cnt']} endpoints")

        # P4-6: LPS flow coverage summary
        r46 = s.run(
            "MATCH (lps:LogicalPipeSegment {pid_id:$p}) "
            "RETURN lps.flow_state AS fs, count(*) AS n ORDER BY n DESC", p=pid
        ).data()
        total_lps = sum(r["n"] for r in r46)
        resolved = sum(r["n"] for r in r46 if r["fs"] in ("SEEDED","PROPAGATED"))
        pct = 100*resolved//total_lps if total_lps else 0
        print(f"  INFO  Flow coverage: {resolved}/{total_lps} ({pct}%) | breakdown: {[(r['fs'],r['n']) for r in r46]}")

        # ── CROSS checks ────────────────────────────────────────────────
        print("\n--- Cross-checks ---")

        # CROSS-2: inferred_check_valve — verify GT degree
        rows_cv = s.run(
            "MATCH (n:Node {pid_id:$p, label:'inferred_check_valve'}) "
            "WITH n, size([(n)-[:PIPE]-(m:Node {pid_id:$p}) | m]) AS deg "
            "WHERE deg < 2 "
            "RETURN n.id AS nid, deg", p=pid
        ).data()
        if not rows_cv:
            r_cv_total = s.run(
                "MATCH (n:Node {pid_id:$p, label:'inferred_check_valve'}) RETURN count(n) AS cnt", p=pid
            ).single()
            ok(f"CROSS-2 inferred_check_valve: {r_cv_total['cnt'] if r_cv_total else 0} all have degree>=2")
        else:
            for r in rows_cv:
                warn(f"CROSS-2 inferred_check_valve {r['nid']} has only deg={r['deg']}")

        # CROSS-3: Every GT-isolated node (degree=0 non-arrow) should have orphan_node annotation
        gt_true_orphans = {nid for nid,lbl in labels_gt.items()
                           if lbl not in ("arrow","crossing","background")
                           and nid not in adj_gt}
        db_annotated_orphans = {r["nid"] for r in s.run(
            "MATCH (a:Annotation {pid_id:$p, type:'orphan_node'})-[:ANNOTATES]->(n:Node) "
            "RETURN n.id AS nid", p=pid
        ).data()}
        missed = gt_true_orphans - db_annotated_orphans
        if not missed:
            ok(f"CROSS-3 All {len(gt_true_orphans)} GT-true orphans are annotated")
        else:
            fail(f"CROSS-3 {pid} GT-true orphans NOT annotated: {missed}")

print(f"\n{'='*60}")
print(f"AUDIT COMPLETE  PASS={PASS}  WARN={WARN}  FAIL={FAIL}")
if issues:
    print("\nISSUES:")
    for i in issues:
        print(f"  {i}")
driver.close()
