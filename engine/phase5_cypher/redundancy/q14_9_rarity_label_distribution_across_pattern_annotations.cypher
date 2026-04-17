// ============================================================================
// Question 14.9 — 14. Redundancy & Rarity Patterns
// Engineer question: "Show the rarity label distribution across all pattern annotations."
//
// Operation: count
// Intent: redundancy_patterns
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id}) WHERE ann.rarity_label IS NOT NULL RETURN ann.rarity_label, count(*) AS total ORDER BY total DESC
