// ============================================================================
// Question 3.11 — 3. Instrument Attachment
// Engineer question: "Show instruments grouped by component (pipe segment)."
//
// Operation: list
// Required keywords: component
// Intent: instrument_attachment
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps:PipeSegment {pid_id:$pid_id})-[:CONTAINS]->(n:Node {label:'instrumentation', pid_id:$pid_id})
RETURN ps.id AS pipe_segment_id, collect(n.id) AS instruments
ORDER BY ps.id LIMIT 50
