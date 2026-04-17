// ============================================================================
// Question 5.14 — 5. Logical Pipe Segments
// Engineer question: "What is the flow state breakdown across all LPS?"
//
// Operation: count
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (lps:LogicalPipeSegment {pid_id:$pid_id}) RETURN lps.flow_state AS flow_state, count(lps) AS state_count ORDER BY state_count DESC
