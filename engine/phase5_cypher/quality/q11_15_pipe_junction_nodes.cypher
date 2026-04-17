// ============================================================================
// Question 11.15 — 11. Structural Anomalies
// Engineer question: "Show all pipe junction nodes."
//
// Operation: list
// Required keywords: junction
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'pipe_junction', pid_id:$pid_id})-[:ANNOTATES]->(n:Node {pid_id:$pid_id}) RETURN n.id, n.label, ann.degree
LIMIT 50
