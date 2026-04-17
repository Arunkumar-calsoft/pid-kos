// ============================================================================
// Question 14.6 — 14. Redundancy & Rarity Patterns
// Engineer question: "Show dominant patterns."
//
// Operation: list
// Intent: redundancy_patterns
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {rarity_label:'dominant', pid_id:$pid_id}) RETURN ann.id, ann.type, ann.absolute_count, ann.normalized_ratio
LIMIT 50
