// Q4.10: How many segments have no corresponding logical pipe segment?
// Section: 4. Pipe Segments (Physical)
// Operation: count
// Intent: line_attributes
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'pipe_segment_no_logical_mapping'
RETURN count(ann) AS no_logical_mapping_count
