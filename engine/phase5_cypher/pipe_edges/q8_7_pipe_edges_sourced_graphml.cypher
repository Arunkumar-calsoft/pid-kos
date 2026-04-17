// ============================================================================
// Question 8.7 — 8. Edge-Level Flow (PIPE Relationship)
// Engineer question: "Are all PIPE edges sourced from graphml?"
//
// Operation: validate
// Intent: connectivity_topology
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Node {pid_id:$pid_id})-[r:PIPE]-(b:Node) WHERE r.source <> 'graphml' RETURN count(r) AS non_graphml_count
