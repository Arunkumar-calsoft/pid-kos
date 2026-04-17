// Q4.1: How many pipe segments are there?
// Section: 4. Pipe Segments (Physical)
// Operation: count
// Intent: line_attributes
MATCH (ps:PipeSegment {pid_id: $pid_id})
RETURN count(ps) AS pipe_segment_count
