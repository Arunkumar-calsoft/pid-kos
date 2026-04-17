// ============================================================================
// Question 6.4 — 6. Flow Direction & Arrow Evidence
// Engineer question: "Show all FLOW_EVIDENCE relationships and their confidence scores."
//
// Operation: list
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Arrow {pid_id:$pid_id})-[r:FLOW_EVIDENCE]->(lps) RETURN a.id, lps.id, r.confidence, r.cosine_alignment, r.direction_hint
LIMIT 50
