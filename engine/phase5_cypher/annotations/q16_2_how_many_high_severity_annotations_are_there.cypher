// Q16.2: How many HIGH-severity annotations are there?
// Section: 16. Annotation Triage & Metadata
// Operation: count
// Intent: cross_domain
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.hitl_severity = 'HIGH'
RETURN count(ann) AS high_severity_count
