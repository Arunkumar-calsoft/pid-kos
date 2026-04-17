// ============================================================================
// Question 13.13 — 13. Drawing Consistency & Annotation Requests
// Engineer question: "Show a breakdown of requests by anomaly type."
//
// Operation: count
// Required keywords: breakdown
// Intent: annotation_requests
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ar:AnnotationRequest {pid_id:$pid_id}) RETURN ar.anomaly_type, count(*) AS n ORDER BY n DESC
