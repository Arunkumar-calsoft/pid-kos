// ===================================================================
// 02_which_equipment_items_structurally_in_series.cypher (CORRECTED)
// ===================================================================

// Required keywords: series
MATCH (e1:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)<-[:ENDPOINT_OF]-(e2:Node)
WHERE e1.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND e2.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND e1.id < e2.id
WITH e1, e2, count(DISTINCT lps) AS shared_lps_count
WHERE shared_lps_count = 1
RETURN
  e1.id                     AS equipment_A,
  e2.id                     AS equipment_B,
  'SERIES (structural)'     AS relationship_type
ORDER BY equipment_A, equipment_B
LIMIT 300;
