// Q11.12: Are there any large manifold nodes (degree ≥ 10)?
// Section: 11. Structural Anomalies
// Operation: count
// Intent: drawing_consistency
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'large_manifold_node'
RETURN count(ann) AS manifold_count
