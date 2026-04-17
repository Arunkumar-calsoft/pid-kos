// ============================================================================
// Question 5.6 — 5. Logical Pipe Segments
// Engineer question: "Show all LPS with REVERSE flow direction."
//
// Operation: list
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (lps:LogicalPipeSegment {flow_direction:'REVERSE', pid_id:$pid_id}) RETURN lps.id, lps.flow_confidence
LIMIT 50
