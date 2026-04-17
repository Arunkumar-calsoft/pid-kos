// Q14.7: How many rare motif local annotations exist?
// Section: 14. Redundancy & Rarity Patterns
// Operation: count
// Intent: redundancy_patterns
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'rare_motif_local'
RETURN count(ann) AS rare_motif_count
