// ============================================================================
// Question 13.1 — 13. Drawing Consistency & Annotation Requests
// Engineer question: "Give me a full drawing quality report."
//
// Operation: list
// Required keywords: report, quality
// Intent: annotation_requests
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ar:AnnotationRequest {pid_id:$pid_id}) RETURN ar.request_id, ar.anomaly_type, ar.label, ar.detail ORDER BY ar.anomaly_type
LIMIT 50
