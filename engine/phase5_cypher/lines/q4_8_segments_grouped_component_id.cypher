// ============================================================================
// Question 4.8 — 4. Pipe Segments (Physical)
// Engineer question: "Show segments grouped by component_id."
//
// Operation: list
// Intent: line_attributes
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps:PipeSegment {pid_id:$pid_id}) RETURN ps.component_id AS component_id, collect(ps.id) AS segments ORDER BY component_id LIMIT 50
