// ============================================================================
// Question 16.12 — 16. Annotation Triage & Metadata
// Engineer question: "Show all flow gap detection annotations for this drawing."
//
// Operation: list
// Required keywords: gap
// Intent: flow_coverage
// Source: PID Question Catalogue v5
// NOTE: direction_evidence_missing is no longer stored as Annotation nodes.
// Gaps are tracked via lps.phase4_hint and lps.flow_state = 'UNKNOWN'.
// ============================================================================

MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
WHERE lps.flow_state = 'UNKNOWN'
RETURN lps.id AS lps_id, lps.flow_state AS flow_state, lps.phase4_hint AS hint
ORDER BY lps.id
LIMIT 50
