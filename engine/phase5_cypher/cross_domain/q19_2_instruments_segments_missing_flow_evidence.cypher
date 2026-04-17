// ============================================================================
// Question 19.2 — 19. Cross-Domain & Combined Questions
// Engineer question: "Which instruments are on segments with missing flow evidence?"
//
// Operation: list
// Required keywords: instrument, evidence
// Intent: cross_domain
// Source: PID Question Catalogue v5
// NOTE: direction_evidence_missing is now tracked via lps.flow_state = 'UNKNOWN'.
// ============================================================================

MATCH (lps:LogicalPipeSegment {pid_id: $pid_id, flow_state: 'UNKNOWN'})
-[:COVERS]->(ps:PipeSegment)
-[:CONTAINS]->(n:Node {label: 'instrumentation', pid_id: $pid_id})
RETURN DISTINCT n.id, lps.id
LIMIT 50
