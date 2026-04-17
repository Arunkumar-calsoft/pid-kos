// ============================================================================
// Question 19.3 — 19. Cross-Domain & Combined Questions
// Engineer question: "Show tanks connected to valves that have UNKNOWN flow."
//
// Operation: list
// Required keywords: tank, unknown
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (t:Node {label:'tank', pid_id:$pid_id})-[:PIPE*1..20]-(v:Node {label:'valve', pid_id:$pid_id})<-[:CONTAINS]-(ps)<-[:COVERS]-(lps {flow_state:'UNKNOWN'}) RETURN DISTINCT t.id, v.id, lps.id
LIMIT 50
