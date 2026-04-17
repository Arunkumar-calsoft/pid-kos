// ============================================================================
// Question 11.13 — 11. Structural Anomalies
// Engineer question: "Show all large manifold nodes."
//
// Operation: list
// Required keywords: manifold
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'large_manifold_node', pid_id:$pid_id})-[:ANNOTATES]->(n:Node {pid_id:$pid_id}) RETURN n.id, n.label, ann.degree ORDER BY ann.degree DESC
LIMIT 50
