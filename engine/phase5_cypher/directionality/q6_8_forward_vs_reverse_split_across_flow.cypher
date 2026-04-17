// ============================================================================
// Question 6.8 — 6. Flow Direction & Arrow Evidence
// Engineer question: "What is the FORWARD vs REVERSE split across all FLOW_EVIDENCE?"
//
// Operation: count
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Arrow {pid_id:$pid_id})-[r:FLOW_EVIDENCE]->(lps) RETURN r.observed_direction, count(*) AS total ORDER BY total DESC
