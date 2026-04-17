// ============================================================================
// Question 13.10 — 13. Drawing Consistency & Annotation Requests
// Engineer question: "Show annotation requests for connector nodes."
//
// Operation: list
// Required keywords: connector
// Intent: annotation_requests
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ar:AnnotationRequest {label:'connector', pid_id:$pid_id}) RETURN ar.request_id, ar.anomaly_type, ar.detail
LIMIT 50
