// ============================================================================
// Question 3.6 — 3. Instrument Attachment
// Engineer question: "Show all dangling inline instrument annotation requests."
//
// Operation: list
// Required keywords: dangling
// Intent: annotation_requests
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ar:AnnotationRequest {anomaly_type:'DANGLING_INLINE', label:'instrumentation', pid_id:$pid_id}) RETURN ar.node_id, ar.detail
LIMIT 50
