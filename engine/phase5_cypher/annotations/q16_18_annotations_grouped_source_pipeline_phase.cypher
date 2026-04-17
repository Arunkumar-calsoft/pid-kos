// ============================================================================
// Question 16.18 — 16. Annotation Triage & Metadata
// Engineer question: "Show annotations grouped by source pipeline phase."
//
// Operation: count
// Required keywords: pipeline, source
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id}) WHERE ann.source IS NOT NULL RETURN ann.source, count(*) AS total ORDER BY total DESC
