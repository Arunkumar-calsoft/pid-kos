// Q12.5: How many pipe segments are unreachable from flow evidence?
// Section: 12. Flow Evidence Gaps
// Operation: count
// Required keywords: unreachable, many
// Intent: flow_coverage
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'ps_unreachable_from_evidence'
RETURN count(ann) AS unreachable_count
