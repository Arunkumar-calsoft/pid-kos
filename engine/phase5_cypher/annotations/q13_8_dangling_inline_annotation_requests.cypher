// ============================================================================
// Question 13.8 — 13. Drawing Consistency & Annotation Requests
// Engineer question: "Show all dangling inline annotation requests."
//
// Operation: list
// Required keywords: dangling
// Intent: annotation_requests
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ar:AnnotationRequest {anomaly_type:'DANGLING_INLINE', pid_id:$pid_id}) RETURN ar.node_id, ar.label, ar.detail
LIMIT 50
