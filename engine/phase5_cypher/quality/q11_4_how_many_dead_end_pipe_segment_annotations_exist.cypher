// Q11.4: How many dead-end pipe segment annotations exist?
// Section: 11. Structural Anomalies
// Operation: count
// Intent: drawing_consistency
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'dead_end_pipe_segment'
RETURN count(ann) AS dead_end_count
