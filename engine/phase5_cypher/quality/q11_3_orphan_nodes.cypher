// ============================================================================
// Question 11.3 — 11. Structural Anomalies
// Engineer question: "Show all orphan nodes."
//
// Operation: list
// Required keywords: orphan
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'orphan_node', pid_id:$pid_id})-[:ANNOTATES]->(n:Node {pid_id:$pid_id}) RETURN n.id, n.label
LIMIT 50
