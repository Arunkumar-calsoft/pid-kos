// ============================================================================
// Question 19.7 — 19. Cross-Domain & Combined Questions
// Engineer question: "Which instruments are flagged as dangling AND have no flow evidence?"
//
// Operation: list
// Required keywords: dangling, instrument
// Intent: annotation_requests
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (p:PID {pid_id: $pid_id})-[:HAS_ANNOTATION]->(ar:AnnotationRequest)-[:CONCERNS]->(n:Node)
WHERE ar.anomaly_type = 'DANGLING_INLINE' AND n.label = 'instrumentation'
OPTIONAL MATCH (n)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
WHERE lps.flow_state IN ['SEEDED', 'PROPAGATED']
WITH n, ar, lps
WHERE lps IS NULL
RETURN n.id AS instrument_id, ar.detail AS issue_detail
ORDER BY n.id
LIMIT 50
