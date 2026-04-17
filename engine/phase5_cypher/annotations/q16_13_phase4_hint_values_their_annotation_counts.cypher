// ============================================================================
// Question 16.13 — 16. Annotation Triage & Metadata
// Engineer question: "Show all phase4_hint values and their annotation counts."
//
// Operation: count
// Required keywords: phase4, hint
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id}) WHERE ann.phase4_hint IS NOT NULL RETURN ann.phase4_hint, count(*) AS total ORDER BY total DESC
