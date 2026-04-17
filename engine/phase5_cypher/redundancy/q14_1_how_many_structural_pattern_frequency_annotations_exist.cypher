// Q14.1: How many structural pattern frequency annotations exist?
// Section: 14. Redundancy & Rarity Patterns
// Operation: count
// Intent: drawing_consistency
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'structural_pattern_frequency'
RETURN count(ann) AS pattern_frequency_count
