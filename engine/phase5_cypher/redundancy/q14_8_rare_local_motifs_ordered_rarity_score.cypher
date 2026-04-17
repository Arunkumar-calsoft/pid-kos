// ============================================================================
// Question 14.8 — 14. Redundancy & Rarity Patterns
// Engineer question: "Show all rare local motifs ordered by rarity score."
//
// Operation: list
// Intent: redundancy_patterns
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'rare_motif_local', pid_id:$pid_id})-[:ANNOTATES]->(t) RETURN ann.rarity_score, ann.rarity_label, labels(t)[0] AS label, elementId(t) AS element_id ORDER BY ann.rarity_score DESC
LIMIT 50
