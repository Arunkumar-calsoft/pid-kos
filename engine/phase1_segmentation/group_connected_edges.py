# engine/phase1_segmentation/group_connected_edges.py
#
# Groups connected line-like nodes into PipeSegments.
#
# Changes from pid_kos version:
#   - from .detect_line_segments import is_line_node
#     → still a relative import, but now both files live in
#       engine/phase1_segmentation/ so the import is correct.

import networkx as nx
from .detect_line_segments import is_line_node

# Labels treated as structural connectors (collapsed during contraction)
CONNECTOR_LABELS = {"connector", "crossing", "line_mid", "junction"}


# ── Graph Construction ────────────────────────────────────────────────────
def _build_graph(nodes, edges):
    """
    Build an undirected NetworkX graph from node + edge lists.
    Safe against missing keys and duplicate edges.
    """
    G = nx.Graph()

    for n in nodes:
        nid = n.get("id")
        if nid is None:
            continue
        G.add_node(nid, **(n.get("attrs") or {}))

    for e in edges:
        src = e.get("src")
        dst = e.get("dst")
        if src is None or dst is None:
            continue
        if src == dst:
            continue  # avoid self-loop noise
        G.add_edge(src, dst)

    return G


# ── Connector Clustering ──────────────────────────────────────────────────
def _cluster_connectors(G, nodes):
    """
    Finds connected components formed only by connector-type nodes.

    Returns:
        node_to_cluster : dict[node_id -> cluster_id]
        cluster_members : dict[cluster_id -> list[node_ids]]
    """
    connector_nodes = [
        n["id"]
        for n in nodes
        if (n.get("attrs") or {}).get("label", "").lower() in CONNECTOR_LABELS
        and n.get("id") in G
    ]

    if not connector_nodes:
        return {}, {}

    H = G.subgraph(connector_nodes).copy()

    node_to_cluster = {}
    cluster_members = {}

    for idx, component in enumerate(nx.connected_components(H), start=1):
        cid     = f"CL_{idx}"
        members = sorted(component)
        cluster_members[cid] = members
        for nid in members:
            node_to_cluster[nid] = cid

    return node_to_cluster, cluster_members


# ── Graph Contraction ─────────────────────────────────────────────────────
def _contract_graph(G, node_to_cluster):
    """
    Replace connector clusters with super-nodes.
    Preserves all non-clustered nodes.
    """
    Gc = nx.Graph()

    for n in G.nodes:
        Gc.add_node(node_to_cluster.get(n, n))

    for u, v in G.edges:
        cu = node_to_cluster.get(u, u)
        cv = node_to_cluster.get(v, v)
        if cu != cv:
            Gc.add_edge(cu, cv)

    return Gc


# ── Main Entry Point ──────────────────────────────────────────────────────
def group_connected_edges(nodes, edges):
    """
    Groups connected line-like nodes into PipeSegments.

    Returns:
        List[List[node_id]]
    """

    # Phase 1: Build graph
    G = _build_graph(nodes, edges)
    if G.number_of_nodes() == 0:
        return []

    # Phase 2: Connector clustering + contraction
    node_to_cluster, cluster_members = _cluster_connectors(G, nodes)
    Gc = _contract_graph(G, node_to_cluster)

    # Phase 3: Determine line-likeness per contracted node
    node_lookup = {n["id"]: n for n in nodes if "id" in n}
    contracted_is_line = {}

    for n in Gc.nodes:
        if isinstance(n, str) and n.startswith("CL_"):
            # Cluster super-nodes are always line carriers
            contracted_is_line[n] = True
        else:
            orig = node_lookup.get(n)
            contracted_is_line[n] = bool(orig and is_line_node(orig))

    # Phase 4: Traverse contracted graph → build contracted segments
    visited = set()
    contracted_segments = []

    for start in Gc.nodes:
        if not contracted_is_line.get(start, False):
            continue
        if start in visited:
            continue

        path    = [start]
        visited.add(start)
        current = start

        while True:
            neighbors = [
                nbr for nbr in Gc.neighbors(current)
                if nbr not in visited
            ]
            # Stop at dead end or branch
            if len(neighbors) != 1:
                break

            nxt = neighbors[0]
            # Stop at non-line boundary node
            if not contracted_is_line.get(nxt, False):
                break

            path.append(nxt)
            visited.add(nxt)
            current = nxt

        contracted_segments.append(path)

    # Phase 5: Expand connector clusters back to original node ids
    expanded_segments = []

    for seg in contracted_segments:
        expanded = []
        for n in seg:
            if isinstance(n, str) and n.startswith("CL_"):
                expanded.extend(cluster_members.get(n, []))
            else:
                expanded.append(n)

        # De-duplicate while preserving order
        seen    = set()
        ordered = []
        for x in expanded:
            if x not in seen:
                ordered.append(x)
                seen.add(x)

        if ordered:
            expanded_segments.append(ordered)

    return [s for s in expanded_segments if s]