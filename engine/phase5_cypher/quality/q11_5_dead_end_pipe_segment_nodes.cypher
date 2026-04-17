// ============================================================================
// Question 11.5 — 11. Structural Anomalies
// Engineer question: "Show all dead-end pipe segment nodes."
//
// Operation: list
// Required keywords: dead
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'dead_end_pipe_segment', pid_id:$pid_id})-[:ANNOTATES]->(n:Node {pid_id:$pid_id}) RETURN n.id, n.label, ann.degree
LIMIT 50
