// Q11.10: How many structural_high_degree annotations exist?
// Section: 11. Structural Anomalies
// Operation: count
// Intent: drawing_consistency
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'structural_high_degree'
RETURN count(ann) AS high_degree_count
