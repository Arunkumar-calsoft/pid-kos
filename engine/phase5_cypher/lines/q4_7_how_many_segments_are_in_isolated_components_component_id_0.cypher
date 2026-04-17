// Q4.7: How many segments are in isolated components (component_id>0)?
// Section: 4. Pipe Segments (Physical)
// Operation: count
// Intent: isolation_reachability
MATCH (ps:PipeSegment {pid_id: $pid_id})
WHERE ps.component_id > 0
RETURN count(ps) AS isolated_component_count
