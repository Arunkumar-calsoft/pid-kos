// ============================================================================
// Question 2.4 — 2. Valve Placement & Connectivity
// Engineer question: "What is the degree of each valve?"
//
// Operation: list
// Required keywords: degree
// Intent: valve_placement
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (v:Node {pid_id: $pid_id, label: 'valve'})
WITH v, size([(v)-[:PIPE]-(m:Node) | m]) AS degree
RETURN v.id AS valve_id, degree
ORDER BY degree DESC, v.id
LIMIT 50
