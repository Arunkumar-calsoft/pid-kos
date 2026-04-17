// ============================================================================
// Question 13.11 — 13. Drawing Consistency & Annotation Requests
// Engineer question: "Show annotation requests for valve nodes."
//
// Operation: list
// Required keywords: valve
// Intent: annotation_requests
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ar:AnnotationRequest {label:'valve', pid_id:$pid_id}) RETURN ar.request_id, ar.anomaly_type, ar.detail
LIMIT 50
