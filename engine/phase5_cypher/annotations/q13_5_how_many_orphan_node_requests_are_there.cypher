// Q13.5: How many ORPHAN_NODE requests are there?
// Section: 13. Drawing Consistency & Annotation Requests
// Operation: count
// Required keywords: many, orphan
// Intent: annotation_requests
MATCH (ar:AnnotationRequest {pid_id: $pid_id})
WHERE ar.anomaly_type = 'ORPHAN_NODE'
RETURN count(ar) AS orphan_node_request_count
