// ============================================================================
// Question 15.3 — 15. ESV / KAV Annotation Classification
// Engineer question: "Show all ESV annotations ordered by severity."
//
// Operation: list
// Required keywords: esv
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {category:'ESV', pid_id:$pid_id}) RETURN ann.id, ann.type, ann.hitl_severity ORDER BY ann.hitl_severity
LIMIT 50
