// ============================================================================
// Question 5.5 — 5. Logical Pipe Segments
// Engineer question: "Show all pipe segments with FORWARD flow direction."
//
// Operation: list
// Required keywords: forward
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (lps:LogicalPipeSegment {flow_direction:'FORWARD', pid_id:$pid_id}) RETURN lps.id, lps.flow_confidence, lps.flow_source
LIMIT 50
