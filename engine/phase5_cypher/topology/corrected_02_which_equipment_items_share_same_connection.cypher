// ===================================================================
// 02_which_equipment_items_share_same_connection.cypher (CORRECTED)
// ===================================================================

// Required keywords: share
MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})<-[:ENDPOINT_OF]-(e:Node)
WHERE e.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
WITH lps, collect(DISTINCT e.id) AS equipments
WHERE size(equipments) > 1
RETURN
  lps.id                  AS lps_id,
  equipments              AS connected_equipment,
  size(equipments)        AS equipment_count
ORDER BY equipment_count DESC
LIMIT 200;
