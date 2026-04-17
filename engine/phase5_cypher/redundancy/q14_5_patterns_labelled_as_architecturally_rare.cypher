// ============================================================================
// Question 14.5 — 14. Redundancy & Rarity Patterns
// Engineer question: "Show patterns labelled as architecturally rare."
//
// Operation: list
// Intent: redundancy_patterns
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {rarity_label:'architecturally_rare', pid_id:$pid_id}) RETURN ann.id, ann.type, ann.rarity_score
LIMIT 50
