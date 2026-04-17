// ============================================================================
// Question 19.9 — 19. Cross-Domain & Combined Questions
// Engineer question: "Which tank has the most connected LPS?"
//
// Operation: list
// Required keywords: tank
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (t:Node {label:'tank', pid_id:$pid_id})<-[:CONTAINS]-(ps)<-[:COVERS]-(lps) WITH t, count(DISTINCT lps) AS n RETURN t.id, n ORDER BY n DESC
LIMIT 50
