// Q12.1: How many LPS have missing direction evidence (still unresolved after Phase 4)?
// Section: 12. Flow Evidence Gaps
// Operation: count
// Intent: flow_coverage
// NOTE: direction_evidence_missing is now a direct LPS property (phase4_hint), not an Annotation.
// UNKNOWN flow_state is the post-Phase 4 indicator of unresolved flow direction.
MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
WHERE lps.flow_state = 'UNKNOWN'
RETURN count(lps) AS missing_evidence_count
