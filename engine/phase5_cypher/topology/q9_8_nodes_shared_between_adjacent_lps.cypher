// ============================================================================
// Question 9.8 — 9. Connectivity & Topology
// Engineer question: "What nodes are shared between adjacent LPS?"
//
// Operation: list
// Intent: segment_junction_topology
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:LogicalPipeSegment {pid_id:$pid_id})-[r:ADJACENT_VIA_NODES]->(b:LogicalPipeSegment) RETURN a.id AS from_lps, b.id AS to_lps, r.via_nodes AS via_nodes LIMIT 50
