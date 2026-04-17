// ============================================================================
// Question 12.10 — 12. Flow Evidence Gaps
// Engineer question: "Show the direction frequency summary annotation."
//
// Operation: list
// Required keywords: frequency, summary
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'direction_frequency_summary', pid_id:$pid_id}) RETURN ann.id, ann.pattern_type, ann.rarity_score
LIMIT 50
