// ============================================================================
// Question 4.4 — 4. Pipe Segments (Physical)
// Engineer question: "Show the longest pipe segment."
//
// Operation: list
// Intent: line_attributes
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps:PipeSegment {pid_id:$pid_id}) RETURN ps.id, ps.node_count ORDER BY ps.node_count DESC LIMIT 1
