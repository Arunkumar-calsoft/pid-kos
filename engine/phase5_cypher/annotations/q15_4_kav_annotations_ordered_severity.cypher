// ============================================================================
// Question 15.4 — 15. ESV / KAV Annotation Classification
// Engineer question: "Show all KAV annotations ordered by severity."
//
// Operation: list
// Required keywords: kav
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {category:'KAV', pid_id:$pid_id}) RETURN ann.id, ann.type, ann.hitl_severity ORDER BY ann.hitl_severity
LIMIT 50
