// ============================================================================
// Question 3.10 — 3. Instrument Attachment
// Engineer question: "Which pipe segments contain instrument nodes?"
//
// Operation: list
// Required keywords: pipe, segment
// Intent: instrument_attachment
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps:PipeSegment {pid_id:$pid_id})-[:CONTAINS]->(n:Node {label:'instrumentation', pid_id:$pid_id}) RETURN ps.id, n.id
LIMIT 50
