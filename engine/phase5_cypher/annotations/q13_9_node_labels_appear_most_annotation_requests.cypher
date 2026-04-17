// ============================================================================
// Question 13.9 — 13. Drawing Consistency & Annotation Requests
// Engineer question: "Which node labels appear most in annotation requests?"
//
// Operation: count
// Required keywords: label, most
// Intent: annotation_requests
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ar:AnnotationRequest {pid_id:$pid_id}) RETURN ar.label, count(*) AS n ORDER BY n DESC
