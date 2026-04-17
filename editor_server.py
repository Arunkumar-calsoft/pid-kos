#!/usr/bin/env python3
# editor_server.py — KOS-PID GraphML Correction Editor
#
# Standalone Flask server (default port 8081).
# Run:  python editor_server.py [--port 8081]
#
# ── Endpoints ─────────────────────────────────────────────────────────────────
# GET  /                                  editor UI (ui/editor.html)
# GET  /api/pids                          list available PIDs
# GET  /api/image/<pid_id>                raw P&ID image
# GET  /api/nodes/<pid_id>                node list: [id, label, xmin, ymin, w, h, functional_label]
# GET  /api/edges/<pid_id>                PIPE edge pairs: [{source, target}]
# GET  /api/node_props/<pid_id>/<node_id> all Neo4j properties of a single node
# GET  /api/patches/<pid_id>              list all saved patches for a PID
# POST /api/patch                         apply a new patch (Neo4j live + patch file)
# DELETE /api/patch/<pid_id>/<patch_id>   revert a patch (Neo4j undo + remove from file)
# GET  /api/graphml/<pid_id>              download corrected GraphML (patches applied)

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from flask import Flask, Response, jsonify, request, send_file, send_from_directory

from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader
from graphml_editor.patch_store import PatchStore
from graphml_editor.neo4j_patcher import Neo4jPatcher
from graphml_editor.graphml_patcher import apply_patches

# ── Boot ──────────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=str(PROJECT_ROOT / "ui"))

_store_root: str = ""
try:
    with open(PROJECT_ROOT / "config" / "storage.yaml") as f:
        _store_root = yaml.safe_load(f)["storage"]["store_root"]
    print(f"[EDITOR] Store root: {_store_root}")
except Exception as exc:
    print(f"[EDITOR] Warning: storage.yaml — {exc}")

print("[EDITOR] Connecting to Neo4j …")
_loader  = Neo4jLoader()
_patcher = Neo4jPatcher(_loader)
_store   = PatchStore(PROJECT_ROOT / "patches")
print("[EDITOR] Ready.")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_pid_paths(pid_id: str) -> Dict[str, str]:
    with _loader.driver.session(database=_loader.database) as s:
        row = s.run(
            "MATCH (:Plant)-[:HAS_SKID]->(:Skid)-[:HAS_PID]->(pid:PID {pid_id:$pid_id}) "
            "RETURN pid.graphml_path AS gml, pid.image_path AS img",
            pid_id=pid_id,
        ).single()
    if not row:
        raise ValueError(f"PID '{pid_id}' not found in Neo4j")
    gml = os.path.join(_store_root, row["gml"].replace("/", os.sep))
    img = os.path.join(_store_root, row["img"].replace("/", os.sep))
    _store_root_abs = Path(_store_root).resolve()
    try:
        Path(gml).resolve().relative_to(_store_root_abs)
    except ValueError:
        raise ValueError(f"GraphML path escapes store root: {gml}")
    try:
        Path(img).resolve().relative_to(_store_root_abs)
    except ValueError:
        raise ValueError(f"Image path escapes store root: {img}")
    if not os.path.exists(gml):
        raise FileNotFoundError(f"GraphML missing: {gml}")
    if not os.path.exists(img):
        raise FileNotFoundError(f"Image missing: {img}")
    return {"graphml": gml, "image": img}


def _parse_nodes_from_graphml(pid_id: str) -> Dict[str, Any]:
    """Parse node positions from GraphML; augment functional_label from Neo4j."""
    paths  = _resolve_pid_paths(pid_id)
    prefix = "{http://graphml.graphdrawing.org/xmlns}"
    tree   = ET.parse(paths["graphml"])
    root   = tree.getroot()
    keys   = {k.get("id"): k.get("attr.name") for k in root.iter(f"{prefix}key")}
    graph  = root.find(f"{prefix}graph")
    if graph is None:
        return {"canvas": {"w": 0, "h": 0}, "nodes": []}

    all_nodes: List[Dict] = []
    for n in graph.iter(f"{prefix}node"):
        d   = {keys.get(i.get("key"), i.get("key")): i.text for i in n.iter(f"{prefix}data")}
        lbl = d.get("label", "connector")
        try:
            xmin = float(str(d["xmin"]))
            ymin = float(str(d["ymin"]))
            xmax = float(str(d["xmax"]))
            ymax = float(str(d["ymax"]))
        except (KeyError, TypeError, ValueError):
            continue
        all_nodes.append({"id": n.get("id"), "label": lbl, "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax})

    if not all_nodes:
        return {"canvas": {"w": 0, "h": 0}, "nodes": []}

    bg = [n for n in all_nodes if n["label"] == "background"]
    canvas_w = max(n["xmax"] for n in (bg or all_nodes))
    canvas_h = max(n["ymax"] for n in (bg or all_nodes))

    # Pull functional_label from Neo4j so pumps display correctly
    with _loader.driver.session(database=_loader.database) as s:
        rows = s.run(
            "MATCH (n:Node {pid_id: $p}) RETURN n.id AS id, n.functional_label AS fl, n.label AS lbl",
            p=pid_id,
        ).data()
    neo_props = {r["id"]: {"functional_label": r["fl"], "label": r["lbl"]} for r in rows}

    nodes = []
    for n in all_nodes:
        if n["label"] == "background":
            continue
        nprops = neo_props.get(n["id"], {})
        nodes.append({
            "id":             n["id"],
            "label":          nprops.get("label") or n["label"],
            "xmin":           round(n["xmin"], 2),
            "ymin":           round(n["ymin"], 2),
            "w":              round(n["xmax"] - n["xmin"], 2),
            "h":              round(n["ymax"] - n["ymin"], 2),
            "functional_label": nprops.get("functional_label"),
        })
    return {"canvas": {"w": canvas_w, "h": canvas_h}, "nodes": nodes}


def _get_edges(pid_id: str) -> List[Dict[str, str]]:
    """Return deduplicated PIPE edge pairs for the given PID."""
    with _loader.driver.session(database=_loader.database) as s:
        rows = s.run(
            "MATCH (a:Node {pid_id: $p})-[:PIPE]->(b:Node {pid_id: $p}) "
            "RETURN a.id AS source, b.id AS target",
            p=pid_id,
        ).data()
    seen: set = set()
    edges: List[Dict[str, str]] = []
    for r in rows:
        key = tuple(sorted([r["source"], r["target"]]))
        if key not in seen:
            seen.add(key)
            edges.append({"source": r["source"], "target": r["target"]})
    return edges


def _fetch_old_value(pid_id: str, node_id: str, prop_key: str) -> Optional[Any]:
    """Fetch current property value from Neo4j (for undo)."""
    props = _patcher.fetch_node_props(pid_id, node_id)
    if props is None:
        return None
    return props.get(prop_key)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def editor_ui():
    return send_from_directory(str(PROJECT_ROOT / "ui"), "editor.html")


@app.route("/api/pids")
def get_pids():
    try:
        with _loader.driver.session(database=_loader.database) as s:
            rows = s.run("MATCH (pid:PID) RETURN pid.pid_id AS pid_id ORDER BY pid.pid_id").data()
        return jsonify([r["pid_id"] for r in rows])
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/image/<pid_id>")
def get_image(pid_id: str):
    try:
        paths = _resolve_pid_paths(pid_id)
        return send_file(paths["image"])
    except Exception as exc:
        return jsonify({"error": str(exc)}), 404


@app.route("/api/nodes/<pid_id>")
def get_nodes(pid_id: str):
    try:
        return jsonify(_parse_nodes_from_graphml(pid_id))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/edges/<pid_id>")
def get_edges(pid_id: str):
    try:
        return jsonify(_get_edges(pid_id))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/node_props/<pid_id>/<node_id>")
def get_node_props(pid_id: str, node_id: str):
    try:
        props = _patcher.fetch_node_props(pid_id, node_id)
        if props is None:
            return jsonify({"error": "Node not found"}), 404
        # Convert Neo4j types to JSON-safe
        safe = {k: (list(v) if hasattr(v, "__iter__") and not isinstance(v, str) else v)
                for k, v in props.items()}
        return jsonify(safe)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/patches/<pid_id>")
def list_patches(pid_id: str):
    return jsonify(_store.list_patches(pid_id))


@app.route("/api/patch", methods=["POST"])
def apply_patch():
    """
    Apply a new patch.

    Expected JSON body:
        op          str   required
        pid_id      str   required
        node_id     str   required
        target_id   str   required for add_edge / remove_edge
        prop_key    str   required for set_property
        new_value   any   required for relabel / set_property / rename_node
    """
    body = request.get_json(force=True, silent=True) or {}
    op      = body.get("op")
    pid_id  = body.get("pid_id")
    node_id = body.get("node_id")

    if not op or not pid_id or not node_id:
        return jsonify({"error": "op, pid_id, node_id are required"}), 400

    target_id = body.get("target_id")
    prop_key  = body.get("prop_key")
    new_value = body.get("new_value")

    # Fetch old value for undo support
    old_value = None
    if op == "relabel":
        old_value = _fetch_old_value(pid_id, node_id, "label")
    elif op == "set_property" and prop_key:
        old_value = _fetch_old_value(pid_id, node_id, prop_key)
    elif op == "rename_node":
        old_value = node_id

    try:
        patch_rec = _store.add_patch(
            pid_id,
            op,
            node_id,
            target_id=target_id,
            prop_key=prop_key,
            old_value=old_value,
            new_value=new_value,
            applied=False,  # mark false until Neo4j confirms
        )
        _patcher.apply(patch_rec)

        # Mark applied = True in store
        patches = _store.list_patches(pid_id)
        for p in patches:
            if p["patch_id"] == patch_rec["patch_id"]:
                p["applied"] = True
        # Rewrite with updated applied flag
        _store._write(pid_id, patches)
        patch_rec["applied"] = True

        return jsonify({"ok": True, "patch": patch_rec}), 201

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/patch/<pid_id>/<patch_id>", methods=["DELETE"])
def revert_patch(pid_id: str, patch_id: str):
    """Revert a patch: undo Neo4j change + remove from patch file."""
    patch = _store.get_patch(pid_id, patch_id)
    if patch is None:
        return jsonify({"error": "Patch not found"}), 404
    try:
        _patcher.revert(patch)
        _store.remove_patch(pid_id, patch_id)
        return jsonify({"ok": True, "reverted": patch_id})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/graphml/<pid_id>")
def download_graphml(pid_id: str):
    """
    Return a corrected GraphML file with all saved patches applied.
    Suitable for archiving or feeding back into Phase 0 on next ingestion.
    """
    try:
        paths   = _resolve_pid_paths(pid_id)
        patches = _store.list_patches(pid_id)
        corrected_xml = apply_patches(paths["graphml"], patches)
        return Response(
            corrected_xml,
            mimetype="application/xml",
            headers={"Content-Disposition": f'attachment; filename="{pid_id}_corrected.graphml"'},
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KOS-PID GraphML Correction Editor")
    parser.add_argument("--port", type=int, default=8081, help="Port to listen on (default: 8081)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    print(f"[EDITOR] Starting on http://{args.host}:{args.port}/")
    app.run(host=args.host, port=args.port, debug=args.debug)
