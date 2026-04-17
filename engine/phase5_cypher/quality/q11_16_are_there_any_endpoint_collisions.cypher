// Q11.16: Are there any endpoint collisions?
// Section: 11. Structural Anomalies
// Operation: count
// Intent: drawing_consistency
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'endpoint_collision'
RETURN count(ann) AS collision_count
