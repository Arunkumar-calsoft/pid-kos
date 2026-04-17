// Q4.6: How many segments are in the main component (component_id=0)?
// Section: 4. Pipe Segments (Physical)
// Operation: count
// Intent: isolation_reachability
MATCH (ps:PipeSegment {pid_id: $pid_id})
WHERE ps.component_id = 0
RETURN count(ps) AS main_component_count
