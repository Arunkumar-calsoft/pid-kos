// ============================================================================
// Question 3.7 — 3. Instrument Attachment
// Engineer question: "Which instruments are connected to valves?"
//
// Operation: list
// Required keywords: valve
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (i:Node {label:'instrumentation', pid_id:$pid_id})-[:PIPE*1..20]-(v:Node {label:'valve', pid_id:$pid_id}) RETURN DISTINCT i.id, v.id
LIMIT 50
