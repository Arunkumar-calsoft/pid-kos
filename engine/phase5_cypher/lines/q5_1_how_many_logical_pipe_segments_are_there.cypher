// Q5.1: How many logical pipe segments are there?
// Section: 5. Logical Pipe Segments
// Operation: count
// Intent: line_attributes
MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
RETURN count(lps) AS lps_count
