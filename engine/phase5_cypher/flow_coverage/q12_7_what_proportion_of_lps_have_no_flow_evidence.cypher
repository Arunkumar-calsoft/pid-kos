// Q12.7: What proportion of LPS have no flow evidence (still unresolved after Phase 4)?
// Section: 12. Flow Evidence Gaps
// Operation: count
// Required keywords: proportion
// Intent: flow_coverage
// NOTE: direction_evidence_missing is now tracked via lps.flow_state = 'UNKNOWN'.
MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
WITH count(lps) AS total
MATCH (lps2:LogicalPipeSegment {pid_id: $pid_id})
WHERE lps2.flow_state = 'UNKNOWN'
WITH total, count(lps2) AS missing
RETURN missing, total, round(100.0 * missing / total, 1) AS missing_pct
