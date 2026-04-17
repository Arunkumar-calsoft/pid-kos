// ============================================================================
// Question 18.8 — 18. Isolation & Reachability
// Engineer question: "Show connected components by node count."
//
// Operation: list
// Intent: isolation_reachability
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps:PipeSegment {pid_id:$pid_id}) RETURN ps.component_id, sum(ps.node_count) AS total_nodes ORDER BY total_nodes DESC
LIMIT 50
