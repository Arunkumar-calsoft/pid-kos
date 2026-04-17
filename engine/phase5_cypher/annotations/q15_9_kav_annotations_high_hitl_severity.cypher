// ============================================================================
// Question 15.9 — 15. ESV / KAV Annotation Classification
// Engineer question: "Show KAV annotations with HIGH hitl_severity."
//
// Operation: list
// Required keywords: kav
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {category:'KAV', hitl_severity:'HIGH', pid_id:$pid_id}) RETURN ann.id, ann.type
LIMIT 50
