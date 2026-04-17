// ============================================================================
// Question 4.9 — 4. Pipe Segments (Physical)
// Engineer question: "Are there any duplicate geometry_hash segments?"
//
// Operation: count
// Intent: line_attributes
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps:PipeSegment {pid_id:$pid_id}) WITH ps.geometry_hash AS gh, collect(ps.id) AS ids WHERE size(ids)>1 RETURN gh, ids
