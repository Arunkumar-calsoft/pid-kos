// ============================================================================
// Question 19.10 — 19. Cross-Domain & Combined Questions
// Engineer question: "Show ESV annotations on high-degree nodes."
//
// Operation: list
// Required keywords: degree
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {category:'ESV', pid_id:$pid_id})-[:ANNOTATES]->(n:Node {pid_id:$pid_id}) WHERE ann.degree IS NOT NULL AND ann.degree >= 3 RETURN n.id, n.label, ann.type, ann.degree
LIMIT 50
