// ============================================================================
// Question 19.6 — 19. Cross-Domain & Combined Questions
// Engineer question: "Which valves have both a structural annotation and UNKNOWN flow?"
//
// Operation: list
// Required keywords: valve, structural, unknown
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (v:Node {pid_id: $pid_id, label: 'valve'})
WHERE EXISTS { MATCH (ann:Annotation)-[:ANNOTATES]->(v) WHERE ann.type IN ['structural_branch','structural_t_junction','structural_high_degree'] }
MATCH (v)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
WHERE lps.flow_state = 'UNKNOWN'
RETURN DISTINCT v.id AS valve_id, lps.id AS lps_id
ORDER BY v.id
LIMIT 50
