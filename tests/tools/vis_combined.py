#!/usr/bin/env python3
"""
Full P&ID visualization:
- Pipes colored by phase or flow direction
- Arrows highlighted
- Equipment symbols labeled
- Connectors shown
- Annotated segments highlighted
"""

import os
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
CONNECTOR_COLOR = (0.2, 0.45, 0.8, 1.0)
EQUIP_COLOR = (0.13, 0.7, 0.2, 1.0)
ARROW_COLOR = (0.9, 0.2, 0.2, 1.0)
OTHER_COLOR = (0.6, 0.6, 0.6, 1.0)

FLOW_FORWARD_COLOR = (0.1, 0.8, 0.1, 0.8)
FLOW_REVERSE_COLOR = (0.8, 0.1, 0.1, 0.8)
FLOW_UNKNOWN_COLOR = (0.7, 0.7, 0.7, 0.5)
ANNOTATION_COLOR = (0.8, 0.5, 0.8, 0.6)  # semi-transparent purple

FALLBACK_SEGMENT_COLORS = [
    (0.8,0.3,0.3,0.7), (0.3,0.8,0.3,0.7), (0.3,0.3,0.8,0.7),
    (0.8,0.6,0.2,0.7), (0.6,0.2,0.8,0.7), (0.2,0.8,0.6,0.7)
]

# --- Utilities ---
def node_center(attrs):
    try:
        xmin = float(attrs.get("xmin", 0))
        xmax = float(attrs.get("xmax", 0))
        ymin = float(attrs.get("ymin", 0))
        ymax = float(attrs.get("ymax", 0))
        return ((xmin + xmax)/2.0, (ymin + ymax)/2.0)
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

# --- Neo4j ---
def connect_neo4j(cfg_path=NEO4J_CONFIG):
    with open(cfg_path, "r") as f:
        cfg = yaml.safe_load(f).get("neo4j", {})
    driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))
    return driver, cfg.get("database", "kos")

def fetch_all_phase_data(driver, database):
    # Phase1/pipe segments
    with driver.session(database=database) as s:
        res = s.run("MATCH (ps:PipeSegment) RETURN ps.id AS pid")
        phase1_data = {rec["pid"]: "RAINBOW" for rec in res}

    # Phase3 annotated
    with driver.session(database=database) as s:
        res = s.run("""
            MATCH (ps:PipeSegment)<-[:ANNOTATES]-(a:Annotation)
            RETURN ps.id AS pid
        """)
        phase3_data = {rec["pid"]: "ANNOTATED" for rec in res}

    # Phase4 flow
    with driver.session(database=database) as s:
        res = s.run("MATCH (ps:PipeSegment) RETURN ps.id AS pid, ps.flow_direction AS dir")
        phase4_data = {rec["pid"]: rec["dir"] for rec in res if rec["dir"]}

    return phase1_data, phase3_data, phase4_data

# --- Visualization ---
def plot_full_pid(image_path, nodes, edges, phase1_data, phase3_data, phase4_data, out_path):
    img = Image.open(image_path).convert("RGBA")
    W, H = img.size
    fig, ax = plt.subplots(figsize=(W/100,H/100), dpi=100)
    ax.imshow(img)
    ax.set_xlim(0,W)
    ax.set_ylim(H,0)
    ax.axis("off")

    centers = {n["id"]: node_center(n["attrs"]) for n in nodes if node_center(n["attrs"])}

    # Draw base edges
    for e in edges:
        s,d = e["src"], e["dst"]
        if s in centers and d in centers:
            x1,y1 = centers[s]
            x2,y2 = centers[d]
            ax.plot([x1,x2],[y1,y2],color="black",linewidth=1,alpha=0.3)

    # Group nodes by segment
    seg_nodes = defaultdict(list)
    for n in nodes:
        pid = n["attrs"].get("pipe_segment")
        if pid:
            seg_nodes[pid].append(n["id"])

    # --- Draw pipe segments (Phase1 / Phase4 / Phase3 annotations) ---
    color_idx = 0
    for pid, _ in phase1_data.items():
        pts = [centers[nid] for nid in seg_nodes.get(pid,[]) if nid in centers]
        if len(pts) >= 2:
            xs, ys = zip(*pts)
            ax.plot(xs, ys, linewidth=3, color=FALLBACK_SEGMENT_COLORS[color_idx%len(FALLBACK_SEGMENT_COLORS)][:3],
                    alpha=0.6)
        color_idx += 1

    # Overlay flow directions (Phase4)
    for pid, dir in phase4_data.items():
        pts = [centers[nid] for nid in seg_nodes.get(pid,[]) if nid in centers]
        if len(pts) >= 2:
            xs, ys = zip(*pts)
            if dir=="FORWARD":
                col = FLOW_FORWARD_COLOR
            elif dir=="REVERSE":
                col = FLOW_REVERSE_COLOR
            else:
                col = FLOW_UNKNOWN_COLOR
            ax.plot(xs, ys, linewidth=4, color=col[:3], alpha=col[3])

    # Overlay annotations (Phase3)
    for pid in phase3_data.keys():
        pts = [centers[nid] for nid in seg_nodes.get(pid,[]) if nid in centers]
        if len(pts) >= 2:
            xs, ys = zip(*pts)
            ax.plot(xs, ys, linewidth=4, color=ANNOTATION_COLOR[:3], alpha=ANNOTATION_COLOR[3])

    # Draw nodes: equipment, connectors, arrows
    for n in nodes:
        nid = n["id"]
        c = centers.get(nid)
        if not c:
            continue
        x,y = c
        label = safe_lower(n["attrs"].get("label",""))

        # Arrows (Phase2)
        if "arrow" in label:
            ax.scatter([x],[y],s=180,color=ARROW_COLOR[:3],marker="^",zorder=5,alpha=0.9)
            continue

        # Connectors
        if "connector" in label:
            ax.scatter([x],[y],s=40,color=CONNECTOR_COLOR[:3],marker="o",zorder=4)
            continue

        # Equipment / valves / pumps
        if any(k in label for k in ("pump","tank","vessel","valve","instrument","heater","condenser")):
            ax.scatter([x],[y],s=80,color=EQUIP_COLOR[:3],marker="s",zorder=4)
            text = n["attrs"].get("label","")
            if text:
                ax.text(x+3,y-3,text,fontsize=6,color="black",zorder=6)
            continue

        # Other small nodes
        ax.scatter([x],[y],s=25,color=OTHER_COLOR[:3],marker=".",zorder=3)

    fig.tight_layout(pad=0)
    fig.savefig(out_path,bbox_inches="tight",pad_inches=0,dpi=150)
    plt.close(fig)
    print(f"[OK] Full P&ID visualization saved to: {out_path}")

# --- Main ---
def main():
    if not os.path.exists(IMG_PATH) or not os.path.exists(GRAPHML_PATH):
        print("Image or GraphML not found.")
        return

    print("Loading GraphML...")
    nodes, edges = load_graphml(GRAPHML_PATH)
    print(f"Loaded {len(nodes)} nodes, {len(edges)} edges")

    try:
        driver, database = connect_neo4j()
        phase1_data, phase3_data, phase4_data = fetch_all_phase_data(driver, database)
        driver.close()
    except Exception as e:
        print(f"Warning: Neo4j error: {e}")
        phase1_data, phase3_data, phase4_data = {}, {}, {}

    out_path = "full_pid_snapshot.png"
    plot_full_pid(IMG_PATH, nodes, edges, phase1_data, phase3_data, phase4_data, out_path)

if __name__=="__main__":
    main()
