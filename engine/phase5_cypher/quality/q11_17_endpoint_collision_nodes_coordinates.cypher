// ============================================================================
// Question 11.17 — 11. Structural Anomalies
// Engineer question: "Show endpoint collision nodes with coordinates."
//
// Operation: list
// Required keywords: collision, endpoint
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'endpoint_collision', pid_id:$pid_id})-[:ANNOTATES]->(n:Node {pid_id:$pid_id}) RETURN n.id, n.label, n.xmin, n.ymin, n.xmax, n.ymax
LIMIT 50
