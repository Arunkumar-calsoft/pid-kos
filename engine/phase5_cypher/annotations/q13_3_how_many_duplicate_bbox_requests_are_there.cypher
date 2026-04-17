// Q13.3: How many DUPLICATE_BBOX requests are there?
// Section: 13. Drawing Consistency & Annotation Requests
// Operation: count
// Required keywords: many, duplicate
// Intent: annotation_requests
MATCH (ar:AnnotationRequest {pid_id: $pid_id})
WHERE ar.anomaly_type = 'DUPLICATE_BBOX'
RETURN count(ar) AS duplicate_bbox_count
