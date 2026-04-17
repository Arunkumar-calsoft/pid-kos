// ============================================================================
// Question 4.12 — 4. Pipe Segments (Physical)
// Engineer question: "Which segments are part of a pipe loop or cycle?"
//
// Operation: list
// Required keywords: loop
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'pipe_segment_cycle_member', pid_id:$pid_id})-[:ANNOTATES]->(ps:PipeSegment {pid_id:$pid_id}) RETURN ps.id, ann.cycle_length
LIMIT 50
