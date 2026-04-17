// Q13.7: How many DANGLING_INLINE requests are there?
// Section: 13. Drawing Consistency & Annotation Requests
// Operation: count
// Required keywords: many, dangling
// Intent: annotation_requests
MATCH (ar:AnnotationRequest {pid_id: $pid_id})
WHERE ar.anomaly_type = 'DANGLING_INLINE'
RETURN count(ar) AS dangling_inline_count
