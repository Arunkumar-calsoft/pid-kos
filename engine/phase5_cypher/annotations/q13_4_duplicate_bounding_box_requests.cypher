// ============================================================================
// Question 13.4 — 13. Drawing Consistency & Annotation Requests
// Engineer question: "Show all duplicate bounding box requests."
//
// Operation: list
// Required keywords: duplicate, bounding
// Intent: annotation_requests
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ar:AnnotationRequest {anomaly_type:'DUPLICATE_BBOX', pid_id:$pid_id}) RETURN ar.node_id, ar.detail
LIMIT 50
