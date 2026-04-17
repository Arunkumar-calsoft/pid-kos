// ============================================================================
// Question 5.9 — 5. Logical Pipe Segments
// Engineer question: "Show LPS with flow confidence below 0.5."
//
// Operation: list
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (lps:LogicalPipeSegment {pid_id:$pid_id}) WHERE lps.flow_confidence < 0.5 RETURN lps.id, lps.flow_confidence, lps.flow_state
LIMIT 50
