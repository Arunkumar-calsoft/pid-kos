// Q11.8: How many T-junction annotations exist?
// Section: 11. Structural Anomalies
// Operation: count
// Intent: drawing_consistency
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'structural_t_junction'
RETURN count(ann) AS t_junction_count
