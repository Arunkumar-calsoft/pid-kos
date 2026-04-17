// ============================================================================
// Question 3.2 — 3. Instrument Attachment
// Engineer question: "List all instrumentation node IDs."
//
// Operation: list
// Intent: instrument_attachment
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'instrumentation', pid_id:$pid_id}) RETURN n.id
LIMIT 50
