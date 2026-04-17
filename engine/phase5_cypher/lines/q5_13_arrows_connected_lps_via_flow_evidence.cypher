// ============================================================================
// Question 5.13 — 5. Logical Pipe Segments
// Engineer question: "Show which arrows are connected to each LPS via FLOW_EVIDENCE."
//
// Operation: list
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Arrow {pid_id:$pid_id})-[r:FLOW_EVIDENCE]->(lps:LogicalPipeSegment {pid_id:$pid_id}) RETURN a.id, lps.id, r.confidence, r.direction_hint
LIMIT 50
