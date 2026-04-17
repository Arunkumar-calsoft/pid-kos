// ============================================================================
// Question 13.14 — 13. Drawing Consistency & Annotation Requests
// Engineer question: "Show the detail text for all annotation requests."
//
// Operation: list
// Required keywords: detail
// Intent: annotation_requests
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ar:AnnotationRequest {pid_id:$pid_id}) RETURN ar.request_id, ar.anomaly_type, ar.node_id, ar.label, ar.detail
LIMIT 50
