// ============================================================================
// Question 16.14 — 16. Annotation Triage & Metadata
// Engineer question: "Show annotations flagged as requires_fallback_rule_or_hitl."
//
// Operation: list
// Required keywords: fallback
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {phase4_hint:'requires_fallback_rule_or_hitl', pid_id:$pid_id}) RETURN ann.id, ann.type, ann.target_id
LIMIT 50
