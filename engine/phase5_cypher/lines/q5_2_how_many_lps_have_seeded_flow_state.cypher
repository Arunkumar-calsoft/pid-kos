// Q5.2: How many LPS have SEEDED flow state?
// Section: 5. Logical Pipe Segments
// Operation: count
// Intent: line_attributes
MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
WHERE lps.flow_state = 'SEEDED'
RETURN count(lps) AS seeded_count
