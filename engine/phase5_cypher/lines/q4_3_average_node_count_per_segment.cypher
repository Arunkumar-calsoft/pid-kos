// ============================================================================
// Question 4.3 — 4. Pipe Segments (Physical)
// Engineer question: "What is the average node count per segment?"
//
// Operation: count
// Intent: line_attributes
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps:PipeSegment {pid_id:$pid_id}) RETURN avg(ps.node_count) AS avg_node_count
