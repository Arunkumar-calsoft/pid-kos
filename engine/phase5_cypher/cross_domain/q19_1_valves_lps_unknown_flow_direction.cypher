// ============================================================================
// Question 19.1 — 19. Cross-Domain & Combined Questions
// Engineer question: "Which valves are on LPS with UNKNOWN flow direction?"
//
// Operation: list
// Required keywords: valve, unknown
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (lps:LogicalPipeSegment {pid_id:$pid_id, flow_state:'UNKNOWN'})-[:COVERS]->(ps:PipeSegment)-[:CONTAINS]->(v:Node {label:'valve'})
RETURN DISTINCT v.id AS valve_id, lps.id AS lps_id, lps.flow_state AS flow_state
LIMIT 50
