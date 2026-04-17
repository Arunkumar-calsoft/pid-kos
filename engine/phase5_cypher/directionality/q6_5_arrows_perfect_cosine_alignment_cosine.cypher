// ============================================================================
// Question 6.5 — 6. Flow Direction & Arrow Evidence
// Engineer question: "Show arrows with perfect cosine alignment (|cosine|=1.0)."
//
// Operation: list
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Arrow {pid_id: $pid_id})-[fe:FLOW_EVIDENCE]->(lps:LogicalPipeSegment)
WHERE abs(fe.cosine_alignment) = 1.0
RETURN a.id AS arrow_id, lps.id AS lps_id, fe.cosine_alignment AS cosine,
       fe.confidence AS confidence, fe.direction_hint AS direction
ORDER BY a.id
LIMIT 50
