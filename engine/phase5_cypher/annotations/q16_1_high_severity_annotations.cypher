// ============================================================================
// Question 16.1 — 16. Annotation Triage & Metadata
// Engineer question: "Show all HIGH-severity annotations."
//
// Operation: list
// Required keywords: high, severity
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {hitl_severity:'HIGH', pid_id:$pid_id}) RETURN ann.id, ann.type, ann.audience, ann.source ORDER BY ann.type
LIMIT 50
