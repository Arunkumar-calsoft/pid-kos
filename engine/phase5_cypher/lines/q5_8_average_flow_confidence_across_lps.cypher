// ============================================================================
// Question 5.8 — 5. Logical Pipe Segments
// Engineer question: "What is the average flow confidence across all LPS?"
//
// Operation: count
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (lps:LogicalPipeSegment {pid_id:$pid_id}) RETURN avg(lps.flow_confidence) AS avg_flow_confidence
