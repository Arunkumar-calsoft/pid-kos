// ============================================================================
// Question 13.12 — 13. Drawing Consistency & Annotation Requests
// Engineer question: "Which specific nodes are flagged by annotation requests?"
//
// Operation: list
// Required keywords: specific, flagged
// Intent: annotation_requests
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ar:AnnotationRequest {pid_id:$pid_id})-[:CONCERNS]->(n:Node {pid_id:$pid_id}) RETURN ar.anomaly_type, n.id, n.label, ar.detail
LIMIT 50
