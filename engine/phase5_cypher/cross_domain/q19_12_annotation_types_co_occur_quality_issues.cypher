// ============================================================================
// Question 19.12 — 19. Cross-Domain & Combined Questions
// Engineer question: "Show annotation types that co-occur with quality issues on the same node."
//
// Operation: list
// Required keywords: occur, co
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n)<-[:ANNOTATES]-(a1:Annotation {pid_id:$pid_id}), (n)<-[:ANNOTATES]-(a2:Annotation {pid_id:$pid_id}) WHERE a1<>a2 RETURN a1.type, a2.type, count(*) AS co ORDER BY co DESC
LIMIT 50
