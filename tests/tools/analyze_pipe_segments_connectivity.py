"""
tools/analyze_pipe_segments_connectivity.py

Connectivity analysis for PipeSegments with full reasoning traces.

What this version does:
 - Uses precomputed JOINS_AT relationships (two_hop, multihop)
 - Tracks reasoning for each edge using trace_nodes property
 - Reports orphan nodes (not in any PipeSegment) and isolated PipeSegments
 - Prints connected components and sample edge traces
 - Non-destructive: does not modify the database
"""

from ingestion.load_to_neo4j import Neo4jLoader
import networkx as nx

MAX_SAMPLE = 10  # Max nodes/segments per component to print

def fetch_pipe_segments(loader):
    """Return all PipeSegment IDs"""
    with loader.driver.session(database=loader.database) as s:
        rows = s.run("MATCH (ps:PipeSegment) RETURN ps.id AS id").data()
        return [r["id"] for r in rows]

def fetch_orphan_nodes(loader):
    """Count Nodes not contained in any PipeSegment"""
    with loader.driver.session(database=loader.database) as s:
        return s.run("""
            MATCH (n:Node)
            WHERE NOT (n)<-[:CONTAINS]-(:PipeSegment)
            RETURN count(n) AS cnt
        """).single()["cnt"]

def fetch_joins_at_edges(loader):
    """
    Fetch all PipeSegment JOINS_AT relationships.
    Returns a list of dicts:
        {"ps1": id1, "ps2": id2, "kind": kind, "trace_nodes": [...]}
    """
    edges = []
    with loader.driver.session(database=loader.database) as s:
        rows = s.run("""
            MATCH (ps1:PipeSegment)-[j:JOINS_AT]->(ps2:PipeSegment)
            RETURN ps1.id AS ps1, ps2.id AS ps2, j.kind AS kind, j.trace_nodes AS trace
        """).data()
        for r in rows:
            edges.append({
                "ps1": r["ps1"],
                "ps2": r["ps2"],
                "kind": r["kind"],
                "trace_nodes": r["trace"]
            })
    return edges

def analyze(loader):
    # Fetch PipeSegments
    ps_ids = fetch_pipe_segments(loader)
    print(f"[INFO] Total PipeSegments: {len(ps_ids)}")

    # Orphan Nodes
    orphan_nodes = fetch_orphan_nodes(loader)
    print(f"[INFO] Orphan nodes (not in any PipeSegment): {orphan_nodes}")

    # Fetch JOINS_AT edges
    ps_edges = fetch_joins_at_edges(loader)
    print(f"[INFO] Total JOINS_AT edges: {len(ps_edges)}")

    # Build connectivity graph
    G = nx.Graph()
    for ps in ps_ids:
        G.add_node(ps)
    for e in ps_edges:
        G.add_edge(e["ps1"], e["ps2"], kind=e["kind"], trace_nodes=e["trace_nodes"])

    # Analyze connected components
    components = list(nx.connected_components(G))
    num_components = len(components)
    largest_cc = max(len(c) for c in components) if components else 0
    isolated = [n for n, d in G.degree() if d == 0]

    print(f"[INFO] Connected components: {num_components}")
    print(f"[INFO] Largest connected component size: {largest_cc}")
    print(f"[INFO] Isolated PipeSegments: {len(isolated)} (sample: {isolated[:MAX_SAMPLE]})")

    if num_components > 1:
        print("[WARN] Multiple disconnected components detected:")
        components_sorted = sorted(components, key=lambda c: -len(c))
        for i, comp in enumerate(components_sorted[:MAX_SAMPLE]):
            sample = list(comp)[:MAX_SAMPLE]
            print(f"  Component {i+1}: {len(comp)} PipeSegments (sample: {sample})")
    else:
        print("[INFO] All PipeSegments are connected into a single network.")

    # Show sample edge traces
    print("[DEBUG] Sample edge traces:")
    for e in ps_edges[:MAX_SAMPLE]:
        print(f"  {e['ps1']} -> {e['ps2']} | kind={e['kind']} | trace_nodes={e['trace_nodes']}")

    # Return structured report
    return {
        "total_pipe_segments": len(ps_ids),
        "orphan_nodes": orphan_nodes,
        "adjacency_edges": len(ps_edges),
        "num_components": num_components,
        "largest_cc": largest_cc,
        "isolated_count": len(isolated),
        "edges_with_trace": ps_edges[:MAX_SAMPLE],
    }

if __name__ == "__main__":
    loader = Neo4jLoader()
    try:
        analyze(loader)
    finally:
        loader.close()
