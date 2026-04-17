// ============================================================================
// Question 2.10 — 2. Valve Placement & Connectivity
// Engineer question: "Which valves are on LPS with FORWARD flow?"
//
// Operation: list
// Required keywords: forward
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (v:Node {pid_id: $pid_id, label: 'valve'})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
WHERE lps.flow_direction = 'FORWARD'
RETURN v.id AS valve_id, lps.id AS lps_id, lps.flow_confidence AS confidence
ORDER BY v.id
LIMIT 50
