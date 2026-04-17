// ============================================================================
// Question 14.4 — 14. Redundancy & Rarity Patterns
// Engineer question: "Show all structurally rare pattern annotations."
//
// Operation: list
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'structural_pattern_rarity', pid_id:$pid_id}) RETURN ann.id, ann.rarity_label, ann.rarity_score, ann.pattern_type ORDER BY ann.rarity_score DESC
LIMIT 50
