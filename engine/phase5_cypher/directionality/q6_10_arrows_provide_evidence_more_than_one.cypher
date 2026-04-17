// ============================================================================
// Question 6.10 — 6. Flow Direction & Arrow Evidence
// Engineer question: "Which arrows provide evidence for more than one LPS?"
//
// Operation: list
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (e:Evidence {pid_id:$pid_id})-[:ABOUT]->(lps:LogicalPipeSegment) WHERE e.arrow_id IS NOT NULL WITH e.arrow_id AS arrow, count(DISTINCT lps) AS n WHERE n > 1 RETURN arrow, n AS lps_count ORDER BY n DESC LIMIT 50
