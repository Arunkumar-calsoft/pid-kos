// ============================================================================
// Question 13.6 — 13. Drawing Consistency & Annotation Requests
// Engineer question: "Show all orphan node annotation requests."
//
// Operation: list
// Required keywords: orphan
// Intent: annotation_requests
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ar:AnnotationRequest {anomaly_type:'ORPHAN_NODE', pid_id:$pid_id}) RETURN ar.node_id, ar.label, ar.detail
LIMIT 50
