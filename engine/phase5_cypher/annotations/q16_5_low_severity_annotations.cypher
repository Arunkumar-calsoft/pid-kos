// ============================================================================
// Question 16.5 — 16. Annotation Triage & Metadata
// Engineer question: "Show LOW-severity annotations."
//
// Operation: list
// Required keywords: low, severity
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {hitl_severity:'LOW', pid_id:$pid_id}) RETURN ann.id, ann.type
LIMIT 50
