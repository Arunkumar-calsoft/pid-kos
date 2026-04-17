// ============================================================================
// Question 18.5 — 18. Isolation & Reachability
// Engineer question: "What are the confirmed isolated component IDs?"
//
// Operation: list
// Intent: isolation_reachability
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps:PipeSegment {pid_id:$pid_id}) WHERE ps.component_id > 0 RETURN DISTINCT ps.component_id ORDER BY ps.component_id
LIMIT 50
