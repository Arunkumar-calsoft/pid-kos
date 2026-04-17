// ============================================================================
// Question 4.5 — 4. Pipe Segments (Physical)
// Engineer question: "Show the shortest pipe segment."
//
// Operation: list
// Intent: line_attributes
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps:PipeSegment {pid_id:$pid_id}) RETURN ps.id, ps.node_count ORDER BY ps.node_count ASC LIMIT 1
