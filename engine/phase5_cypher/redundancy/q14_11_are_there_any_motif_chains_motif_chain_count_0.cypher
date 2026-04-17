// Q14.11: Are there any motif chains (motif_chain_count > 0)?
// Section: 14. Redundancy & Rarity Patterns
// Operation: count
// Intent: redundancy_patterns
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.motif_chain_count > 0
RETURN count(ann) AS chain_count
