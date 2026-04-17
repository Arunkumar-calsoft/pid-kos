// ============================================================================
// Question 19.8 — 19. Cross-Domain & Combined Questions
// Engineer question: "Show all nodes with more than one quality annotation."
//
// Operation: list
// Required keywords: multiple, quality
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n)<-[:ANNOTATES]-(ann:Annotation {pid_id:$pid_id}) WITH n, count(ann) AS cnt WHERE cnt > 1 RETURN labels(n)[0] AS node_label, elementId(n) AS element_id, cnt ORDER BY cnt DESC
LIMIT 50
