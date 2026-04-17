// ============================================================================
// Question 2.6 — 2. Valve Placement & Connectivity
// Engineer question: "Which valves are directly connected to tanks?"
//
// Operation: list
// Required keywords: tank
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (v:Node {label:'valve', pid_id:$pid_id})-[:PIPE*1..20]-(t:Node {label:'tank', pid_id:$pid_id}) RETURN DISTINCT v.id, t.id
LIMIT 50
