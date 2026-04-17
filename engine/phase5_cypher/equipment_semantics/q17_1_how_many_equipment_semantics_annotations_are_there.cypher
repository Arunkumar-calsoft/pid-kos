// Q17.1: How many equipment semantics annotations are there?
// Section: 17. Equipment Semantics
// Operation: count
// Intent: cross_domain
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.intent = 'equipment_semantics'
RETURN count(ann) AS equipment_semantics_count
