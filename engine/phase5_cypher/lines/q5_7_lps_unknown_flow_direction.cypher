// ============================================================================
// Question 5.7 — 5. Logical Pipe Segments
// Engineer question: "Show all LPS with UNKNOWN flow direction."
//
// Operation: list
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (lps:LogicalPipeSegment {flow_state:'UNKNOWN', pid_id:$pid_id}) RETURN lps.id, lps.flow_source
LIMIT 50
