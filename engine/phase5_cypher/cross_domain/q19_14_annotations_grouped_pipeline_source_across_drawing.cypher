// ============================================================================
// Question 19.14 — 19. Cross-Domain & Combined Questions
// Engineer question: "Show annotations grouped by pipeline source across this drawing."
//
// Operation: count
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id}) RETURN ann.source, count(*) AS total ORDER BY total DESC
