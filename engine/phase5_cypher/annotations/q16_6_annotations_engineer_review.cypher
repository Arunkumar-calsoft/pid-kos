// ============================================================================
// Question 16.6 — 16. Annotation Triage & Metadata
// Engineer question: "Show annotations for engineer review."
//
// Operation: list
// Required keywords: review
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {audience:'engineer_review', pid_id:$pid_id}) RETURN ann.id, ann.type, ann.hitl_severity ORDER BY ann.hitl_severity
LIMIT 50
