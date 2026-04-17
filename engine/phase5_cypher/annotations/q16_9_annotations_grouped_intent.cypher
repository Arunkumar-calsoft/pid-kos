// ============================================================================
// Question 16.9 — 16. Annotation Triage & Metadata
// Engineer question: "Show annotations grouped by intent."
//
// Operation: count
// Required keywords: intent, grouped
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id}) WHERE ann.intent IS NOT NULL RETURN ann.intent, count(*) AS total ORDER BY total DESC
