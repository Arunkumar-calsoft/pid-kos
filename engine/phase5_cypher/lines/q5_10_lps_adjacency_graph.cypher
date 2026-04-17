// ============================================================================
// Question 5.10 — 5. Logical Pipe Segments
// Engineer question: "Show the LPS adjacency graph."
//
// Operation: list
// Intent: line_attributes
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:LogicalPipeSegment {pid_id:$pid_id})-[r:ADJACENT_VIA_NODES]->(b:LogicalPipeSegment {pid_id:$pid_id}) RETURN a.id, b.id, r.via_nodes
LIMIT 50
