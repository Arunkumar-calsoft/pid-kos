// ============================================================================
// Question 2.7 — 2. Valve Placement & Connectivity
// Engineer question: "Which valves are directly connected to instruments?"
//
// Operation: list
// Required keywords: instrument
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (v:Node {label:'valve', pid_id:$pid_id})-[:PIPE*1..20]-(i:Node {label:'instrumentation', pid_id:$pid_id}) RETURN DISTINCT v.id, i.id
LIMIT 50
