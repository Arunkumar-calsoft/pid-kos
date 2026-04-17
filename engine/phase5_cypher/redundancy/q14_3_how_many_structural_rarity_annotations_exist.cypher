// Q14.3: How many structural rarity annotations exist?
// Section: 14. Redundancy & Rarity Patterns
// Operation: count
// Intent: drawing_consistency
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'structural_pattern_rarity'
RETURN count(ann) AS pattern_rarity_count
