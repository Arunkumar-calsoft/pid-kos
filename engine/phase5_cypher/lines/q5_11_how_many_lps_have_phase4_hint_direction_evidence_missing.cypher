// Q5.11: How many LPS have phase4_hint='direction_evidence_missing'?
// Section: 5. Logical Pipe Segments
// Operation: count
// Intent: cross_domain
MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
WHERE lps.phase4_hint = 'direction_evidence_missing'
RETURN count(lps) AS direction_evidence_missing_count
