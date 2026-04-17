// ============================================================================
// Question 11.19 — 11. Structural Anomalies
// Engineer question: "Show all pipe segments forming a loop."
//
// Operation: list
// Required keywords: loop
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'pipe_segment_cycle_member', pid_id:$pid_id})-[:ANNOTATES]->(ps:PipeSegment {pid_id:$pid_id}) RETURN ps.id, ann.cycle_length
LIMIT 50
