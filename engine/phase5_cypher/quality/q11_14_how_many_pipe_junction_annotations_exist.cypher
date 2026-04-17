// Q11.14: How many pipe junction annotations exist?
// Section: 11. Structural Anomalies
// Operation: count
// Intent: drawing_consistency
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'pipe_junction'
RETURN count(ann) AS pipe_junction_count
