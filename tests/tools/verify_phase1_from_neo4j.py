#!/usr/bin/env python3
"""
verify_phase1_from_neo4j.py

Verify Phase-1 PipeSegments (persisted in Neo4j) against Phase-0 GraphML connector/crossing nodes.

Outputs:
 - overlay image (overlay_phase1_vs_graphml.png)
 - CSV report (verify_phase1_report.csv) with skipped nodes per segment
 - optional JSON dump of pipe segments (phase1_segments.json)
"""

import os
import argparse
import json
import csv
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from PIL import Image, ImageDraw
import yaml
from neo4j import GraphDatabase

# ----------------------------
# Load Neo4j config
# ----------------------------
CONFIG_PATH = os.path.join("config", "neo4j.yaml")
with open(CONFIG_PATH, "r") as f:
    cfg = yaml.safe_load(f)

neo_cfg = cfg.get("neo4j", {})
NEO4J_URI = neo_cfg.get("uri", "bolt://127.0.0.1:7687")
NEO4J_USER = neo_cfg.get("user", "neo4j")
NEO4J_PASSWORD = neo_cfg.get("password", "")
NEO4J_DB = neo_cfg.get("database", "neo4j")

# ----------------------------
# GraphML parsing
# ----------------------------
def parse_graphml(graphml_path):
    ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
    tree = ET.parse(graphml_path)
    root = tree.getroot()

    nodes = {}
    edges = []

    for node in root.findall(".//g:node", ns):
        nid = node.get("id")
        attrs = {}
        for d in node.findall("g:data", ns):
            key = d.get("key")
            text = d.text.strip() if d.text else None
            if text is not None:
                try:
                    attrs[key] = float(text)
                except Exception:
                    attrs[key] = text
        label = str(attrs.get("d0", "")).lower()
        try:
            xmin = float(attrs.get("d1"))
            xmax = float(attrs.get("d2"))
            ymin = float(attrs.get("d3"))
            ymax = float(attrs.get("d4"))
            cx = (xmin + xmax) / 2
            cy = (ymin + ymax) / 2
        except Exception:
            xmin = xmax = ymin = ymax = cx = cy = None

        nodes[nid] = {
            "id": nid,
            "label": label,
            "xmin": xmin,
            "xmax": xmax,
            "ymin": ymin,
            "ymax": ymax,
            "cx": cx,
            "cy": cy,
            "attrs": attrs,
        }

    for edge in root.findall(".//g:edge", ns):
        s = edge.get("source")
        t = edge.get("target")
        edges.append((s, t))

    return nodes, edges

# ----------------------------
# Neo4j accessor
# ----------------------------
class Neo4jAccessor:
    def __init__(self, uri, user, password, database="neo4j"):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    def fetch_pipe_segments(self):
        segs = []
        node_to_segs = defaultdict(list)
        with self.driver.session(database=self.database) as session:
            query = """
            MATCH (ps:PipeSegment)
            OPTIONAL MATCH (ps)-[:CONTAINS]->(n:Node)
            RETURN ps.id AS ps_id, collect(n.id) AS node_ids
            ORDER BY ps.id
            """
            result = session.run(query)
            for record in result:
                ps_id = record["ps_id"]
                node_ids = record["node_ids"] or []
                segs.append({"ps_id": ps_id, "node_ids": node_ids})
                for nid in node_ids:
                    node_to_segs[nid].append(ps_id)
        return segs, node_to_segs

    def close(self):
        if self.driver is not None:
            self.driver.close()

# ----------------------------
# BFS shortest path for skipped node detection
# ----------------------------
def bfs_shortest_path(adj, start, end):
    queue = deque([[start]])
    visited = set([start])
    while queue:
        path = queue.popleft()
        node = path[-1]
        if node == end:
            return path
        for nbr in adj[node]:
            if nbr not in visited:
                visited.add(nbr)
                queue.append(path + [nbr])
    return []

# ----------------------------
# Visualization + CSV
# ----------------------------
def draw_overlay(image_path, nodes, covered_set, uncovered_set, bypassed_edges, out_path):
    img = Image.open(image_path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    R = 6
    COLOR_COVERED = (40, 140, 90, 220)
    COLOR_UNCOVERED = (220, 40, 40, 180)
    COLOR_BYPASSED = (255, 165, 0, 200)  # orange

    for nid, n in nodes.items():
        cx, cy = n["cx"], n["cy"]
        if cx is None or cy is None:
            continue
        if nid in covered_set:
            draw.ellipse((cx-R, cy-R, cx+R, cy+R), fill=COLOR_COVERED)
        elif nid in uncovered_set:
            draw.ellipse((cx-R, cy-R, cx+R, cy+R), fill=COLOR_UNCOVERED)

    for a, b in bypassed_edges:
        if nodes[a]["cx"] is not None and nodes[b]["cx"] is not None:
            draw.line((nodes[a]["cx"], nodes[a]["cy"], nodes[b]["cx"], nodes[b]["cy"]),
                      fill=COLOR_BYPASSED, width=3)

    img.save(out_path)
    print(f"[OK] Overlay saved → {out_path}")

def write_csv(path, summary, fn_sample, segment_skipped_nodes):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        for k, v in summary.items():
            w.writerow([k, v])
        w.writerow([])
        w.writerow(["false_negatives_sample"])
        for item in fn_sample:
            w.writerow([item])
        w.writerow([])
        w.writerow(["pipe_segment", "skipped_nodes"])
        for ps_id, skipped in segment_skipped_nodes.items():
            w.writerow([ps_id, ", ".join(skipped)])
    print(f"[OK] CSV written → {path}")

# ----------------------------
# Main
# ----------------------------
def main(args):
    os.makedirs(args.out_dir, exist_ok=True)

    # Phase-0 GraphML
    print("[INFO] Parsing GraphML ...")
    nodes, edges = parse_graphml(args.graphml)
    graphml_candidates = {nid for nid, n in nodes.items() if n["label"] in {"connector", "crossing"}}
    print(f"[INFO] GraphML connector/crossing nodes: {len(graphml_candidates)}")

    # Build adjacency map for BFS
    graph_adj = defaultdict(set)
    for u, v in edges:
        if u in graphml_candidates and v in graphml_candidates:
            graph_adj[u].add(v)
            graph_adj[v].add(u)

    # Neo4j Phase-1 PipeSegments
    print("[INFO] Connecting to Neo4j ...")
    accessor = Neo4jAccessor(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DB)
    try:
        segments, node_to_segments = accessor.fetch_pipe_segments()
    finally:
        accessor.close()
    print(f"[INFO] PipeSegments fetched: {len(segments)}")

    if args.dump_json:
        out_json = os.path.join(args.out_dir, "phase1_segments.json")
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump(segments, fh, indent=2)
        print(f"[OK] Phase-1 segments dumped → {out_json}")

    # Coverage
    covered_nodes = {nid for nid in graphml_candidates if nid in node_to_segments}
    uncovered_nodes = graphml_candidates - covered_nodes

    # Skipped nodes per segment
    bypassed_edges = []
    segment_skipped_nodes = defaultdict(list)
    for seg in segments:
        node_ids = [nid for nid in seg["node_ids"] if nid in graphml_candidates]
        for i in range(len(node_ids) - 1):
            a, b = node_ids[i], node_ids[i+1]
            path = bfs_shortest_path(graph_adj, a, b)
            if not path:
                bypassed_edges.append((a, b))
                continue
            # skipped nodes: intermediate nodes not in segment
            skipped = [nid for nid in path[1:-1] if nid not in node_ids]
            segment_skipped_nodes[seg["ps_id"]].extend(skipped)
            if skipped:
                bypassed_edges.append((a, b))

    summary = {
        "total_nodes_in_graphml": len(nodes),
        "graphml_candidates": len(graphml_candidates),
        "pipe_segments_total": len(segments),
        "covered_nodes": len(covered_nodes),
        "uncovered_nodes": len(uncovered_nodes),
        "bypassed_edges": len(bypassed_edges),
    }

    # Overlay
    if args.image and os.path.exists(args.image):
        draw_overlay(
            args.image,
            nodes,
            covered_nodes,
            uncovered_nodes,
            bypassed_edges,
            os.path.join(args.out_dir, "overlay_phase1_vs_graphml.png")
        )
    else:
        print("[WARN] Image not provided or not found; skipping overlay.")

    fn_sample = list(uncovered_nodes)[: args.sample]
    write_csv(os.path.join(args.out_dir, "verify_phase1_report.csv"), summary, fn_sample, segment_skipped_nodes)

    print("\n========== PHASE1 VERIFICATION SUMMARY ==========")
    for k, v in summary.items():
        print(f"{k:30s}: {v}")
    print("===============================================")

# ----------------------------
# CLI
# ----------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify Phase1 PipeSegments from Neo4j against GraphML")
    parser.add_argument("--graphml", default="data/2.graphml", help="Path to GraphML")
    parser.add_argument("--image", default="data/2.png", help="Background image (optional)")
    parser.add_argument("--out-dir", default="temp_verify", help="Output folder")
    parser.add_argument("--sample", type=int, default=20, help="Number of FN samples in CSV")
    parser.add_argument("--dump-json", action="store_true", help="Dump Phase1 segments to JSON")
    args = parser.parse_args()
    main(args)
