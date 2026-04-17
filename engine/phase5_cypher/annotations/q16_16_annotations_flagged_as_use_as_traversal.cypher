// ============================================================================
// Question 16.16 — 16. Annotation Triage & Metadata
// Engineer question: "Show annotations flagged as use_as_traversal_index."
//
// Operation: list
// Required keywords: traversal
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {phase4_hint:'use_as_traversal_index', pid_id:$pid_id}) RETURN ann.id, ann.type
LIMIT 50
