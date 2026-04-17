// ============================================================================
// Question 10.7 — 10. External Interfaces
// Engineer question: "Show the LPS each external interface belongs to."
//
// Operation: list
// Intent: external_interfaces
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'inlet/outlet', pid_id:$pid_id})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$pid_id}) RETURN n.id, lps.id, lps.flow_direction
LIMIT 50
