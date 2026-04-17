// ============================================================================
// Question 15.8 — 15. ESV / KAV Annotation Classification
// Engineer question: "Show ESV annotations with HIGH hitl_severity."
//
// Operation: list
// Required keywords: esv
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {category:'ESV', hitl_severity:'HIGH', pid_id:$pid_id}) RETURN ann.id, ann.type
LIMIT 50
