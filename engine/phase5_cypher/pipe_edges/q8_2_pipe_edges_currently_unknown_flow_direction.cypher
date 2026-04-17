// ============================================================================
// Question 8.2 — 8. Edge-Level Flow (PIPE Relationship)
// Engineer question: "Are all PIPE edges currently UNKNOWN flow direction?"
//
// Operation: validate
// Intent: connectivity_topology
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Node {pid_id:$pid_id})-[r:PIPE]-(b:Node) WHERE r.flow_direction <> 'UNKNOWN' RETURN count(r) AS resolved_flow_count
