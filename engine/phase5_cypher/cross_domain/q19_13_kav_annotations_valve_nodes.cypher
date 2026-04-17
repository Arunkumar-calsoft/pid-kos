// ============================================================================
// Question 19.13 — 19. Cross-Domain & Combined Questions
// Engineer question: "Show all KAV annotations on valve nodes."
//
// Operation: list
// Required keywords: valve
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {category:'KAV', pid_id:$pid_id})-[:ANNOTATES]->(n:Node {label:'valve', pid_id:$pid_id}) RETURN n.id, ann.type, ann.hitl_severity
LIMIT 50
