// Q11.6: How many structural branch annotations exist?
// Section: 11. Structural Anomalies
// Operation: count
// Intent: drawing_consistency
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'structural_branch'
RETURN count(ann) AS branch_count
