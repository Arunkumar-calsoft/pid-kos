// ============================================================================
// Question 6.13 — 6. Flow Direction & Arrow Evidence
// Engineer question: "Show Evidence nodes from topology inference."
//
// Operation: list
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (e:Evidence {source:'phase3_topology_inference', pid_id:$pid_id}) RETURN e.id, e.inferred_from, e.direction
LIMIT 50
