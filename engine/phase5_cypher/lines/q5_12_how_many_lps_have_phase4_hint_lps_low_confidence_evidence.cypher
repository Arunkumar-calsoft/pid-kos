// Q5.12: How many LPS have phase4_hint='lps_low_confidence_evidence'?
// Section: 5. Logical Pipe Segments
// Operation: count
// Intent: cross_domain
MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
WHERE lps.phase4_hint = 'lps_low_confidence_evidence'
RETURN count(lps) AS low_confidence_evidence_count
