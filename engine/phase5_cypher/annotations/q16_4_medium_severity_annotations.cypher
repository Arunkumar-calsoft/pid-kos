// ============================================================================
// Question 16.4 — 16. Annotation Triage & Metadata
// Engineer question: "Show MEDIUM-severity annotations."
//
// Operation: list
// Required keywords: medium, severity
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {hitl_severity:'MEDIUM', pid_id:$pid_id}) RETURN ann.id, ann.type, ann.audience
LIMIT 50
