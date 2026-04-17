// ============================================================================
// Question 11.7 — 11. Structural Anomalies
// Engineer question: "Show all structural branch nodes."
//
// Operation: list
// Required keywords: branch
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'structural_branch', pid_id:$pid_id})-[:ANNOTATES]->(n:Node {pid_id:$pid_id}) RETURN n.id, n.label, ann.degree
LIMIT 50
