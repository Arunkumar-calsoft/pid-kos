// ============================================================================
// Question 8.1 — 8. Edge-Level Flow (PIPE Relationship)
// Engineer question: "How many PIPE edges are there?"
//
// Operation: count
// Intent: connectivity_topology
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Node {pid_id:$pid_id})-[r:PIPE]-(b:Node) RETURN count(r) AS total_pipe_relationships
