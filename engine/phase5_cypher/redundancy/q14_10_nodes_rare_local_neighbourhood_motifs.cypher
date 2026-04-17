// ============================================================================
// Question 14.10 — 14. Redundancy & Rarity Patterns
// Engineer question: "Show nodes with rare local neighbourhood motifs."
//
// Operation: list
// Intent: redundancy_patterns
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'rare_motif_local', pid_id:$pid_id})-[:ANNOTATES]->(n:Node {pid_id:$pid_id}) WHERE ann.rarity_label IN ['architecturally_rare','uncommon'] RETURN n.id, n.label, ann.rarity_score
LIMIT 50
