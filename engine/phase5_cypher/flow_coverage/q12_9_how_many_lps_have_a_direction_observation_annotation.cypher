// Q12.9: How many LPS have a direction observation annotation?
// Section: 12. Flow Evidence Gaps
// Operation: count
// Intent: flow_coverage
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'direction_observation'
RETURN count(ann) AS direction_observation_count
