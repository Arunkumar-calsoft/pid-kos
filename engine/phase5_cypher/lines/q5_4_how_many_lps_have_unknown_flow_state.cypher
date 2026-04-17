// Q5.4: How many LPS have UNKNOWN flow state?
// Section: 5. Logical Pipe Segments
// Operation: count
// Intent: line_attributes
MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
WHERE lps.flow_state = 'UNKNOWN'
RETURN count(lps) AS unknown_count
