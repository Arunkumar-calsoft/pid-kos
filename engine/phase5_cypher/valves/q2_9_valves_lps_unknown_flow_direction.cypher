// ============================================================================
// Question 2.9 — 2. Valve Placement & Connectivity
// Engineer question: "Which valves are on LPS with UNKNOWN flow direction?"
//
// Operation: list
// Required keywords: unknown
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (v:Node {pid_id: $pid_id, label: 'valve'})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
WHERE lps.flow_state = 'UNKNOWN'
RETURN v.id AS valve_id, lps.id AS lps_id, lps.flow_state AS flow_state
ORDER BY v.id
LIMIT 50
