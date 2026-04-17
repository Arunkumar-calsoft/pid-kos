// Q13.2: How many open annotation requests are there?
// Section: 13. Drawing Consistency & Annotation Requests
// Operation: count
// Required keywords: open, many
// Intent: annotation_requests
MATCH (ar:AnnotationRequest {pid_id: $pid_id})
WHERE ar.status = 'OPEN'
RETURN count(ar) AS open_request_count
