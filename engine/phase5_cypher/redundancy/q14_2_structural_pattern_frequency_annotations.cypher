// ============================================================================
// Question 14.2 — 14. Redundancy & Rarity Patterns
// Engineer question: "Show all structural pattern frequency annotations."
//
// Operation: list
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'structural_pattern_frequency', pid_id:$pid_id}) RETURN ann.id, ann.absolute_count, ann.normalized_ratio, ann.pattern_type ORDER BY ann.absolute_count DESC
LIMIT 50
