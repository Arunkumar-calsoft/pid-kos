// Q11.2: How many orphan nodes are there?
// Section: 11. Structural Anomalies
// Operation: count
// Required keywords: many
// Intent: drawing_consistency
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'orphan_node'
RETURN count(ann) AS orphan_count
