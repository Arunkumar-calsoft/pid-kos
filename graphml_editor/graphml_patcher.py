# graphml_editor/graphml_patcher.py
#
# Applies a patch list to a GraphML file to produce a corrected copy.
#
# ADMIN USE ONLY — this module is part of the standalone editor tool.
# It is NOT imported by the main pipeline (server.py, engine/, agent/).
#
# The corrected GraphML produced here is the admin's ground-truth edit.
# Feed it back to Phase 0 as the new source file when re-ingesting.
#
# Usage:
#   corrected_xml = apply_patches(graphml_path, patches)
#   Path("corrected_PID_0.graphml").write_text(corrected_xml, encoding="utf-8")
#
# Supported ops (matches neo4j_patcher.py)
# ─────────────────────────────────────────
# add_edge       Appends <edge> element with source/target
# remove_edge    Removes matching <edge> element(s) (both directions)
# relabel        Updates the 'label' data element of the node
# set_property   Updates / creates a data element for the given property name
# rename_node    Updates node id attr + all edge source/target refs
#
# GraphML XML structure assumed
# ─────────────────────────────
# <graphml xmlns="http://graphml.graphdrawing.org/xmlns">
#   <key id="d0" attr.name="label" for="node"/>
#   ...
#   <graph id="G" edgedefault="undirected">
#     <node id="valve1"> <data key="d0">valve</data> ... </node>
#     <edge id="e1" source="valve1" target="connector2"/>
#   </graph>
# </graphml>

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

_NS  = "http://graphml.graphdrawing.org/xmlns"
_PFX = f"{{{_NS}}}"

# Register so serialisation omits redundant namespace declarations
ET.register_namespace("", _NS)


def apply_patches(graphml_path: str | Path, patches: List[Dict]) -> str:
    """
    Parse *graphml_path*, apply every patch in *patches* in order, and
    return the corrected GraphML as a UTF-8 XML string.

    The original file is never modified.
    """
    tree = ET.parse(str(graphml_path))
    root = tree.getroot()

    # ── Build key maps ────────────────────────────────────────────────────────
    # key_map : attr.name  → key id   (for writing data elements)
    key_map: Dict[str, str] = {}
    for k in root.iter(f"{_PFX}key"):
        attr_name = k.get("attr.name", "")
        kid       = k.get("id", "")
        if attr_name and kid:
            key_map[attr_name] = kid

    graph = root.find(f"{_PFX}graph")
    if graph is None:
        return _to_string(root)

    # ── Build node index ──────────────────────────────────────────────────────
    node_map: Dict[str, ET.Element] = {}
    for n in graph.findall(f"{_PFX}node"):
        nid = n.get("id")
        if nid:
            node_map[nid] = n

    # ── Apply patches in order ────────────────────────────────────────────────
    for patch in patches:
        op  = patch.get("op")
        nid = patch.get("node_id")
        tid = patch.get("target_id")
        key = patch.get("prop_key")
        val = patch.get("new_value")
        old = patch.get("old_value")
        pid = patch.get("patch_id") or str(uuid.uuid4())

        if op == "add_edge":
            if nid and tid:
                edge = ET.SubElement(graph, f"{_PFX}edge")
                edge.set("id",     f"patch_{pid}")
                edge.set("source", str(nid))
                edge.set("target", str(tid))

        elif op == "remove_edge":
            to_remove = [
                e for e in graph.findall(f"{_PFX}edge")
                if (e.get("source") == nid and e.get("target") == tid)
                or (e.get("source") == tid and e.get("target") == nid)
            ]
            for e in to_remove:
                graph.remove(e)

        elif op == "relabel":
            node_el = node_map.get(str(nid))
            if node_el is not None:
                _set_data(node_el, key_map.get("label"), str(val))

        elif op == "set_property":
            node_el = node_map.get(str(nid))
            if node_el is not None and key:
                _set_data(node_el, key_map.get(str(key)), str(val))

        elif op == "rename_node":
            old_id  = str(old) if old is not None else str(nid)
            new_id  = str(val)
            node_el = node_map.get(old_id)
            if node_el is not None:
                node_el.set("id", new_id)
                # Update all edge source/target references
                for edge in graph.findall(f"{_PFX}edge"):
                    if edge.get("source") == old_id:
                        edge.set("source", new_id)
                    if edge.get("target") == old_id:
                        edge.set("target", new_id)
                node_map[new_id] = node_el
                node_map.pop(old_id, None)

    return _to_string(root)


def write_corrected(graphml_path: str | Path, patches: List[Dict], out_path: str | Path) -> Path:
    """
    Convenience wrapper: apply patches and write to *out_path*.
    Returns the output path.
    """
    corrected = apply_patches(graphml_path, patches)
    out = Path(out_path)
    out.write_text(corrected, encoding="utf-8")
    return out


# ── Helpers ───────────────────────────────────────────────────────────────────

def _set_data(node_el: ET.Element, key_id: Optional[str], value: str) -> None:
    """Update an existing <data key="…"> element or append a new one."""
    if key_id is None:
        return
    for data in node_el.findall(f"{_PFX}data"):
        if data.get("key") == key_id:
            data.text = value
            return
    data = ET.SubElement(node_el, f"{_PFX}data")
    data.set("key", key_id)
    data.text = value


def _to_string(root: ET.Element) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode", xml_declaration=False
    )
