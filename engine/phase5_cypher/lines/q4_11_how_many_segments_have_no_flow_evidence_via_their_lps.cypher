// Q4.11: How many segments have no flow evidence via their LPS?
// Section: 4. Pipe Segments (Physical)
// Operation: count
// Intent: flow_coverage
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.type = 'pipe_segment_no_evidence_via_lps'
RETURN count(ann) AS no_evidence_via_lps_count
