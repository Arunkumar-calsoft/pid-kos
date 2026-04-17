# engine/phase0_ingestion/parse_graphml.py
#
# CHANGES FROM ORIGINAL:
#   - Detect coord_system per node ('float' | 'int') from raw XML key set
#     before networkx collapses d1/d5 both into 'xmin'.
#     Stored as attrs['coord_system'] for Phase 2 image-crop alignment.
#   - Removed unsafe float() coercion on all attrs — only numeric fields
#     are coerced; string attrs (label, edge_label) are preserved as-is.

import xml.etree.ElementTree as ET
import networkx as nx


# Keys that use the float coordinate system (equipment, arrows)
_FLOAT_COORD_KEYS = {"d1", "d2", "d3", "d4"}

# Keys that use the integer coordinate system (connectors, crossings)
_INT_COORD_KEYS = {"d5", "d6", "d7", "d8"}


def _detect_coord_system(raw_keys: set) -> str:
    """
    Return 'float' if node uses d1-d4 bbox keys,
           'int'   if node uses d5-d8 bbox keys,
           'none'  if node has no spatial data at all.

    Must be called on the raw XML key set BEFORE networkx
    resolves key IDs to attr names — networkx collapses both
    d1 and d5 into 'xmin', losing this distinction.
    """
    if raw_keys & _FLOAT_COORD_KEYS:
        return "float"
    if raw_keys & _INT_COORD_KEYS:
        return "int"
    return "none"


def parse_graphml(path: str):
    """
    Parse GraphML into raw node and edge dictionaries.

    Guarantees:
    - Node IDs preserved exactly as strings
    - All attributes preserved with correct types
    - coord_system provenance stored per node ('float' | 'int' | 'none')
    - Edges treated as undirected adjacency only
    - edge_label preserved as string
    """

    print(f"[PHASE 0][PARSE] Reading GraphML: {path}")

    # ── Pass 1: detect coord_system per node from raw XML ──────────────────
    # Must happen before networkx reads the file, because networkx collapses
    # duplicate attr.name keys (d1 xmin double + d5 xmin long → both 'xmin').
    coord_system_map = {}

    tree = ET.parse(path)
    xml_root = tree.getroot()
    ns = {"g": "http://graphml.graphdrawing.org/xmlns"}

    for node_el in xml_root.findall(".//g:node", ns):
        nid = node_el.get("id")
        raw_keys = {d.get("key") for d in node_el.findall("g:data", ns)}
        coord_system_map[nid] = _detect_coord_system(raw_keys)

    # ── Pass 2: full parse via networkx ────────────────────────────────────
    G = nx.read_graphml(path)

    print(
        f"[PHASE 0][PARSE] Graph loaded | "
        f"nodes={G.number_of_nodes()} edges={G.number_of_edges()}"
    )

    nodes = []
    edges = []

    # ---- Nodes ----
    for node_id, data in G.nodes(data=True):
        attrs = {}

        for k, v in data.items():
            if k == "label":
                # label is always a string — never coerce
                attrs[k] = v
            else:
                # Coerce numeric fields; preserve anything else as-is
                try:
                    attrs[k] = float(v)
                except (ValueError, TypeError):
                    attrs[k] = v

        if "label" not in attrs:
            print(f"[WARN][PARSE] Node {node_id} missing label attribute")

        # Attach coord_system provenance resolved from raw XML
        attrs["coord_system"] = coord_system_map.get(str(node_id), "none")

        nodes.append({
            "id": str(node_id),
            "attrs": attrs,
        })

    # ---- Edges ----
    for src, dst, data in G.edges(data=True):
        attrs = {}
        for k, v in data.items():
            # edge_label is always a string
            attrs[k] = v
        edges.append({
            "src": str(src),
            "dst": str(dst),
            "attrs": attrs,
        })

    # ── Summary logging ────────────────────────────────────────────────────
    float_count = sum(1 for n in nodes if n["attrs"]["coord_system"] == "float")
    int_count   = sum(1 for n in nodes if n["attrs"]["coord_system"] == "int")
    none_count  = sum(1 for n in nodes if n["attrs"]["coord_system"] == "none")

    print(f"[PHASE 0][PARSE] Parsed {len(nodes)} nodes | "
          f"coord_system: float={float_count}, int={int_count}, none={none_count}")
    print(f"[PHASE 0][PARSE] Parsed {len(edges)} edges")

    if nodes:
        print("[PHASE 0][PARSE] Sample node:", nodes[0])
    if edges:
        print("[PHASE 0][PARSE] Sample edge:", edges[0])

    return nodes, edges