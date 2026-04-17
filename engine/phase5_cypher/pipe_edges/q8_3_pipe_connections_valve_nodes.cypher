// ============================================================================
// Question 8.3 — 8. Edge-Level Flow (PIPE Relationship)
// Engineer question: "Show all PIPE connections from valve nodes."
//
// Operation: list
// Intent: connectivity_topology
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (v:Node {label:'valve', pid_id:$pid_id})-[r:PIPE]-(n:Node) RETURN v.id, n.id, n.label
LIMIT 50
