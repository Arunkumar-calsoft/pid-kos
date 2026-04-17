// ============================================================================
// Question 3.8 — 3. Instrument Attachment
// Engineer question: "Which instruments are connected to tanks?"
//
// Operation: list
// Required keywords: tank
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (i:Node {label:'instrumentation', pid_id:$pid_id})-[:PIPE*1..20]-(t:Node {label:'tank', pid_id:$pid_id}) RETURN DISTINCT i.id, t.id
LIMIT 50
