// ============================================================================
// Question 8.4 — 8. Edge-Level Flow (PIPE Relationship)
// Engineer question: "Show all PIPE connections from tank nodes."
//
// Operation: list
// Intent: connectivity_topology
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (t:Node {label:'tank', pid_id:$pid_id})-[r:PIPE]-(n:Node) RETURN t.id, n.id, n.label ORDER BY t.id
LIMIT 50
