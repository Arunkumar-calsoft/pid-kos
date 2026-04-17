// ============================================================================
// Question 9.1 — 9. Connectivity & Topology
// Engineer question: "Which node has the most PIPE connections on this drawing?"
//
// Operation: list
// Intent: connectivity_topology
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {pid_id:$pid_id}) WHERE n.label <> 'background' WITH n, size([(n)-[:PIPE]-() |1]) AS deg RETURN n.id, n.label, deg ORDER BY deg DESC LIMIT 5
