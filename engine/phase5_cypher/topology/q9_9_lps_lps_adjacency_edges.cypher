// ============================================================================
// Question 9.9 — 9. Connectivity & Topology
// Engineer question: "How many LPS-to-LPS adjacency edges are there?"
//
// Operation: count
// Intent: engineering_inventory
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:LogicalPipeSegment {pid_id:$pid_id})-[:ADJACENT_VIA_NODES]->(b:LogicalPipeSegment) RETURN count(*) AS adjacency_count
