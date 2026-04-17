// ============================================================================
// Question 11.11 — 11. Structural Anomalies
// Engineer question: "Show all high-degree nodes with their degree value."
//
// Operation: list
// Required keywords: degree
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'structural_high_degree', pid_id:$pid_id})-[:ANNOTATES]->(n:Node {pid_id:$pid_id}) RETURN n.id, n.label, ann.degree ORDER BY ann.degree DESC
LIMIT 50
