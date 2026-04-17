// ============================================================================
// Question 17.8 — 17. Equipment Semantics
// Engineer question: "Show Evidence nodes inferred from topology."
//
// Operation: list
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (e:Evidence {source:'phase3_topology_inference', pid_id:$pid_id}) RETURN e.id, e.inferred_from, e.direction, e.confidence
LIMIT 50
