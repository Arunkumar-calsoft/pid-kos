// ============================================================================
// Question 19.15 — 19. Cross-Domain & Combined Questions
// Engineer question: "Show valves with high-severity annotations and FORWARD flow."
//
// Operation: list
// Required keywords: forward, valve
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id: $pid_id, hitl_severity: 'HIGH'})-[:ANNOTATES]->(v:Node {label: 'valve'})
MATCH (v)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
WHERE lps.flow_direction = 'FORWARD'
RETURN v.id AS valve_id, ann.type AS annotation_type, ann.hitl_severity AS severity,
       lps.id AS lps_id, lps.flow_confidence AS confidence
ORDER BY v.id
LIMIT 50
