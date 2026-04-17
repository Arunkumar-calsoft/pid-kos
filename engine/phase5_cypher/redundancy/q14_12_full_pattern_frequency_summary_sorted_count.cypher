// ============================================================================
// Question 14.12 — 14. Redundancy & Rarity Patterns
// Engineer question: "Show the full pattern frequency summary sorted by count."
//
// Operation: list
// Intent: engineering_inventory
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id}) WHERE ann.type IN ['structural_pattern_frequency','structural_pattern_rarity'] RETURN ann.type, ann.absolute_count, ann.normalized_ratio, ann.rarity_label ORDER BY ann.absolute_count DESC
LIMIT 50
