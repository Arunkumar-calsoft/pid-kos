// ============================================================================
// Question 4.2 — 4. Pipe Segments (Physical)
// Engineer question: "Show all pipe segments with their node counts."
//
// Operation: list
// Intent: line_attributes
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps:PipeSegment {pid_id:$pid_id}) RETURN ps.id AS id, ps.node_count AS node_count ORDER BY node_count DESC
LIMIT 50
