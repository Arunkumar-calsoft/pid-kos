// Q9.11: Are there pipe loops or cycles in the network?
// Section: 9. Connectivity & Topology
// Operation: validate
// Intent: drawing_consistency
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'pipe_segment_cycle_member'
RETURN count(ann) AS cycle_count
