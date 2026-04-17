// ============================================================================
// Question 12.12 — 12. Flow Evidence Gaps
// Engineer question: "Show all LPS flagged as propagation_blocked and their annotations."
//
// Operation: list
// Required keywords: propagation, blocked
// Intent: flow_coverage
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id: $pid_id, propagation_blocked: true})-[:ANNOTATES]->(lps:LogicalPipeSegment)
RETURN lps.id AS lps_id, ann.type AS annotation_type, ann.phase4_hint AS phase4_hint,
       lps.flow_state AS flow_state
ORDER BY lps.id
LIMIT 50
