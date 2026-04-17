// ============================================================================
// Question 18.12 — 18. Isolation & Reachability
// Engineer question: "Show which LPS are completely isolated (no ADJACENT_VIA_NODES)?"
//
// Operation: list
// Intent: isolation_reachability
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (lps:LogicalPipeSegment {pid_id:$pid_id}) WHERE NOT EXISTS {(lps)-[:ADJACENT_VIA_NODES]-()} RETURN lps.id
LIMIT 50
