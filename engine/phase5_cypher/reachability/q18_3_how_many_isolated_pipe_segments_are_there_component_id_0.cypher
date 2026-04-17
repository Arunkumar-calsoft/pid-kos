// Q18.3: How many isolated pipe segments are there (component_id>0)?
// Section: 18. Isolation & Reachability
// Operation: count
// Intent: isolation_reachability
MATCH (ps:PipeSegment {pid_id: $pid_id})
WHERE ps.component_id > 0
RETURN count(ps) AS isolated_segment_count
