// Q6.3: How many LPS were direction-propagated (no direct arrow)?
// Section: 6. Flow Direction & Arrow Evidence
// Operation: count
// Intent: flow_coverage
MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
WHERE lps.flow_state = 'PROPAGATED'
RETURN count(lps) AS propagated_lps_count
