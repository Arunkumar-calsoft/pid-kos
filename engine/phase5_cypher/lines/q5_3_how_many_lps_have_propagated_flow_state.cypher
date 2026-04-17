// Q5.3: How many LPS have PROPAGATED flow state?
// Section: 5. Logical Pipe Segments
// Operation: count
// Intent: line_attributes
MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
WHERE lps.flow_state = 'PROPAGATED'
RETURN count(lps) AS propagated_count
