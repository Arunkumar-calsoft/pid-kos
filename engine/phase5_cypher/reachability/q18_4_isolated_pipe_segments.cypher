// ============================================================================
// Question 18.4 — 18. Isolation & Reachability
// Engineer question: "Show all isolated pipe segments."
//
// Operation: list
// Intent: isolation_reachability
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps:PipeSegment {pid_id:$pid_id}) WHERE ps.component_id>0 RETURN ps.id, ps.component_id, ps.node_count
LIMIT 50
