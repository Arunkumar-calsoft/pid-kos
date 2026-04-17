// ============================================================================
// Question 16.3 — 16. Annotation Triage & Metadata
// Engineer question: "Show a full severity breakdown."
//
// Operation: count
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id}) WHERE ann.hitl_severity IS NOT NULL RETURN ann.hitl_severity, count(*) AS total ORDER BY total DESC
