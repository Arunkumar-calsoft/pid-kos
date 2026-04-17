// ============================================================================
// Question 11.9 — 11. Structural Anomalies
// Engineer question: "Show all T-junction nodes."
//
// Operation: list
// Required keywords: junction
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'structural_t_junction', pid_id:$pid_id})-[:ANNOTATES]->(n:Node {pid_id:$pid_id}) RETURN n.id, n.label
LIMIT 50
