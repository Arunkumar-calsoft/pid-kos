// Q12.3: How many LPS have low-confidence evidence?
// Section: 12. Flow Evidence Gaps
// Operation: count
// Intent: flow_coverage
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'lps_low_confidence_evidence'
RETURN count(ann) AS low_confidence_count
