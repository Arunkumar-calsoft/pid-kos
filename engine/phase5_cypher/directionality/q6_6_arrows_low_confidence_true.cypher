// ============================================================================
// Question 6.6 — 6. Flow Direction & Arrow Evidence
// Engineer question: "Show arrows with low_confidence=true."
//
// Operation: list
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Arrow {pid_id:$pid_id})-[r:FLOW_EVIDENCE]->(lps) WHERE r.low_confidence=true RETURN a.id, lps.id, r.confidence
LIMIT 50
