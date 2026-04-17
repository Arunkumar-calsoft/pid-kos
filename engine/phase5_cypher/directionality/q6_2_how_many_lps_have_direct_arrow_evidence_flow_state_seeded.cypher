// Q6.2: How many LPS have direct arrow evidence (flow_state='SEEDED')?
// Section: 6. Flow Direction & Arrow Evidence
// Operation: count
// Intent: flow_direction
MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
WHERE lps.flow_state = 'SEEDED'
RETURN count(lps) AS seeded_lps_count
