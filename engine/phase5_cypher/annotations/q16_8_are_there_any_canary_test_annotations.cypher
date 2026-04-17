// Q16.8: Are there any canary test annotations?
// Section: 16. Annotation Triage & Metadata
// Operation: validate
// Intent: cross_domain
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.is_canary = true
RETURN count(ann) AS canary_count
