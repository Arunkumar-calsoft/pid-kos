// ============================================================================
// Question 12.11 — 12. Flow Evidence Gaps
// Engineer question: "Are there any LPS with propagation_blocked=true?"
//
// Operation: list
// Required keywords: propagation, blocked
// Intent: flow_coverage
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {propagation_blocked:true, pid_id:$pid_id})-[:ANNOTATES]->(lps) RETURN lps.id, ann.type, ann.phase4_hint
LIMIT 50
