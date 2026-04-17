// ============================================================================
// Question 12.2 — 12. Flow Evidence Gaps
// Engineer question: "Show all LPS with missing direction evidence."
//
// Operation: list
// Required keywords: missing
// Intent: flow_coverage
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'direction_evidence_missing', pid_id:$pid_id})-[:ANNOTATES]->(lps:LogicalPipeSegment {pid_id:$pid_id}) RETURN lps.id, lps.flow_state, lps.flow_direction
LIMIT 50
