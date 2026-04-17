// ============================================================================
// Question 3.4 — 3. Instrument Attachment
// Engineer question: "Show all orphan node annotations targeting instruments."
//
// Operation: list
// Required keywords: orphan
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id: $pid_id, type: 'orphan_node'})-[:ANNOTATES]->(n:Node)
WHERE n.label = 'instrumentation'
RETURN a.id AS annotation_id, n.id AS instrument_id, a.source AS source
ORDER BY n.id
LIMIT 50
