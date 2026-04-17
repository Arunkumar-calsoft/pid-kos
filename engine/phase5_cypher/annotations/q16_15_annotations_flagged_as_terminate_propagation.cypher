// ============================================================================
// Question 16.15 — 16. Annotation Triage & Metadata
// Engineer question: "Show annotations flagged as terminate_propagation."
//
// Operation: list
// Required keywords: terminate, propagation
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {phase4_hint:'terminate_propagation', pid_id:$pid_id}) RETURN ann.id, ann.type, ann.target_id
LIMIT 50
