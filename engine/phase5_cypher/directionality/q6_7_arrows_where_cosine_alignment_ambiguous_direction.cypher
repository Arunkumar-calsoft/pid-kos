// ============================================================================
// Question 6.7 — 6. Flow Direction & Arrow Evidence
// Engineer question: "Show arrows where |cosine_alignment| < 0.9 (ambiguous direction)."
//
// Operation: list
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Arrow {pid_id: $pid_id})-[fe:FLOW_EVIDENCE]->(lps:LogicalPipeSegment)
WHERE abs(fe.cosine_alignment) < 0.9
RETURN a.id AS arrow_id, lps.id AS lps_id, fe.cosine_alignment AS cosine,
       fe.confidence AS confidence, fe.direction_hint AS direction
ORDER BY abs(fe.cosine_alignment) ASC
LIMIT 50
