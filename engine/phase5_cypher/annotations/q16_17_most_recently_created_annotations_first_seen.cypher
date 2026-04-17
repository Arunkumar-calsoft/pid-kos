// ============================================================================
// Question 16.17 — 16. Annotation Triage & Metadata
// Engineer question: "Show the most recently created annotations (first_seen)."
//
// Operation: list
// Required keywords: recent, created
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id}) WHERE ann.first_seen IS NOT NULL RETURN ann.id, ann.type, ann.first_seen ORDER BY ann.first_seen DESC LIMIT 20
