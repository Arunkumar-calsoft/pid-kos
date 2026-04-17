#!/usr/bin/env python3
"""
tools/vis_phase_mapping.py

Enhanced visual mapping for P&ID phases with flow direction verification.

- Connects to kos Neo4j database.
- Supports modes to verify each phase:
  - phase1: Rainbow-colored PipeSegments (segmentation check)
  - phase2: Highlight arrows (evidence extraction check)
  - phase3: Highlight annotated segments (annotation check)
  - phase4: Flow directions colored (resolution check, green forward, red reverse)
- Arrows: Red triangles
- Equipment: Green squares
- Connectors: Blue circles
- Saves to temp_phase_[mode].png

Usage: python vis_phase_mapping.py --mode phase1
"""

import os
import math
import yaml
import argparse
import networkx as nx
import matplotlib.pyplot as plt
from PIL import Image
from collections import defaultdict

from neo4j import GraphDatabase

# Paths
IMG_PATH = "data/2.png"
GRAPHML_PATH = "data/2.graphml"
NEO4J_CONFIG = "config/neo4j.yaml"

# Colors
CONNECTOR_COLOR = (0.2, 0.45, 0.8, 1.0)   # blue
EQUIP_COLOR = (0.13, 0.7, 0.2, 1.0)       # green
ARROW_COLOR = (0.9, 0.2, 0.2, 1.0)        # red
OTHER_COLOR = (0.6, 0.6, 0.6, 1.0)        # gray

FLOW_FORWARD_COLOR = (0.1, 0.8, 0.1, 0.8)
FLOW_REVERSE_COLOR = (0.8, 0.1, 0.1, 0.8)
FLOW_UNKNOWN_COLOR = (0.7, 0.7, 0.7, 0.5)
ANNOTATION_COLOR = (0.8, 0.5, 0.8, 0.8)   # purple for Phase 3

FALLBACK_SEGMENT_COLORS = [
    (0.8,0.3,0.3,0.7), (0.3,0.8,0.3,0.7), (0.3,0.3,0.8,0.7),
    (0.8,0.6,0.2,0.7), (0.6,0.2,0.8,0.7), (0.2,0.8,0.6,0.7)
]

# Utility functions
def node_center(attrs):
    try:
        xmin = float(attrs.get("xmin", 0))
        xmax = float(attrs.get("xmax", 0))
        ymin = float(attrs.get("ymin", 0))
        ymax = float(attrs.get("ymax", 0))
        return ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)
    except:
        return None

def safe_lower(s):
    return s.lower() if isinstance(s, str) else ""

def load_graphml(path=GRAPHML_PATH):
    G = nx.read_graphml(path)
    nodes, edges = [], []
    for nid, attrs in G.nodes(data=True):
        nodes.append({"id": str(nid), "attrs": dict(attrs)})
    for u, v, a in G.edges(data=True):
        edges.append({"src": str(u), "dst": str(v), "attrs": dict(a)})
    return nodes, edges

# Neo4j connection
def connect_neo4j(cfg_path=NEO4J_CONFIG):
    if not os.path.exists(cfg_path):
        raise FileNotFoundError(f"Neo4j config not found: {cfg_path}")
    with open(cfg_path, "r") as f:
        cfg = yaml.safe_load(f).get("neo4j", {})
    driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))
    return driver, cfg.get("database", "kos")

def fetch_phase_data(driver, database, mode):
    if mode == "phase1":
        # Fetch PipeSegments
        with driver.session(database=database) as s:
            res = s.run("""
                MATCH (ps:PipeSegment)
                RETURN ps.id AS pid
            """)
            return {rec["pid"]: "RAINBOW" for rec in res}  # placeholder for fallback colors

    elif mode == "phase2":
        # Fetch arrows (from raw nodes, since Phase 2 is evidence only)
        return {}  # Phase 2 doesn't write to Neo4j, so use GraphML arrows for highlight

    elif mode == "phase3":
        # Fetch annotated segments
        with driver.session(database=database) as s:
            res = s.run("""
                MATCH (ps:PipeSegment)<-[:ANNOTATES]-(a:Annotation)
                RETURN ps.id AS pid, count(a) AS ann_count
            """)
            return {rec["pid"]: "ANNOTATED" for rec in res}

    elif mode == "phase4":
        # Fetch flow_direction
        with driver.session(database=database) as s:
            res = s.run("""
                MATCH (ps:PipeSegment)
                RETURN ps.id AS pid, ps.flow_direction AS dir
            """)
            return {rec["pid"]: rec["dir"] for rec in res if rec["dir"]}

    return {}

def plot_mapping(image_path, nodes, edges, phase_data, mode, out_path):
    img = Image.open(image_path).convert("RGBA")
    W, H = img.size

    fig, ax = plt.subplots(figsize=(W/100, H/100), dpi=100)
    ax.imshow(img)
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")

    centers = {n["id"]: node_center(n["attrs"]) for n in nodes if node_center(n["attrs"])}

    # Draw edges (base lines)
    for e in edges:
        s, d = e["src"], e["dst"]
        if s in centers and d in centers:
            x1, y1 = centers[s]
            x2, y2 = centers[d]
            ax.plot([x1, x2], [y1, y2], color="black", linewidth=1, alpha=0.5)

    # Group nodes by segment (for Phase 1/3/4)
    seg_nodes = defaultdict(list)
    for n in nodes:
        pid = n["attrs"].get("pipe_segment")  # if available from GraphML
        if pid:
            seg_nodes[pid].append(n["id"])

    # Draw segments by phase mode
    color_idx = 0
    if mode in ["phase1", "phase3", "phase4"]:
        for pid, color_mode in phase_data.items():
            node_list = seg_nodes.get(pid, [])
            pts = [centers[nid] for nid in node_list if nid in centers]
            if len(pts) >= 2:
                xs, ys = zip(*pts)
                if mode == "phase1":
                    col = FALLBACK_SEGMENT_COLORS[color_idx % len(FALLBACK_SEGMENT_COLORS)]
                elif mode == "phase3":
                    col = ANNOTATION_COLOR
                elif mode == "phase4":
                    if color_mode == "FORWARD":
                        col = FLOW_FORWARD_COLOR
                    elif color_mode == "REVERSE":
                        col = FLOW_REVERSE_COLOR
                    else:
                        col = FLOW_UNKNOWN_COLOR
                ax.plot(xs, ys, linewidth=4, color=col[:3], alpha=col[3])
            color_idx += 1

    # Draw nodes
    for n in nodes:
        nid = n["id"]
        c = centers.get(nid)
        if not c:
            continue
        x, y = c
        label = safe_lower(n["attrs"].get("label", ""))

        if mode == "phase2" and "arrow" in label:
            ax.scatter([x], [y], s=200, color=ARROW_COLOR[:3], marker="^", zorder=5, alpha=0.9)  # highlight arrows in phase2
        elif "connector" in label:
            ax.scatter([x], [y], s=40, color=CONNECTOR_COLOR[:3], marker="o", zorder=4)
        elif any(k in label for k in ("pump","tank","vessel","valve","instrument","heater","condenser")):
            ax.scatter([x], [y], s=80, color=EQUIP_COLOR[:3], marker="s", zorder=4)
        else:
            ax.scatter([x], [y], s=25, color=OTHER_COLOR[:3], marker=".", zorder=3)

    fig.tight_layout(pad=0)
    fig.savefig(out_path, bbox_inches='tight', pad_inches=0, dpi=150)
    plt.close(fig)
    print(f"Saved visual mapping for {mode} to: {out_path}")

def main(mode="phase4"):
    if not os.path.exists(IMG_PATH):
        print(f"Image not found: {IMG_PATH}")
        return
    if not os.path.exists(GRAPHML_PATH):
        print(f"GraphML not found: {GRAPHML_PATH}")
        return

    print("Loading GraphML...")
    nodes, edges = load_graphml(GRAPHML_PATH)
    print(f"Loaded {len(nodes)} nodes, {len(edges)} edges")

    try:
        driver, database = connect_neo4j()
        phase_data = fetch_phase_data(driver, database, mode)
        print(f"Fetched data for {mode}: {len(phase_data)} items from Neo4j.")
        driver.close()
    except Exception as e:
        print(f"Warning: Could not connect to Neo4j: {e}")
        phase_data = {}

    out_path = f"temp_phase_{mode}.png"
    plot_mapping(IMG_PATH, nodes, edges, phase_data, mode, out_path)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visualize P&ID phases")
    parser.add_argument("--mode", default="phase4", choices=["phase1", "phase2", "phase3", "phase4"], help="Phase mode to verify")
    args = parser.parse_args()
    main(args.mode)