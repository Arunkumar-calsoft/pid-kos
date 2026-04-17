// Q11.18: Are there pipe loops or cycles?
// Section: 11. Structural Anomalies
// Operation: count
// Intent: drawing_consistency
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'pipe_segment_cycle_member'
RETURN count(ann) AS cycle_count
