// ===================================================================
// 02_directly_connected_equipment_item.cypher (CORRECTED)
// Engineer view: "How are things connected on this P&ID?"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - [:CONNECTED] → [:ENDPOINT_OF]
//   - Added pid_id scoping
//
// Pure topology. No flow meaning. Read-only.
// ===================================================================




/* -------------------------------------------------------------------
1. What is directly connected to each equipment item?
   (Immediate LPS neighbors)
   
   CORRECTED: Shows equipment and their connected LPS endpoints
------------------------------------------------------------------- */




MATCH (e:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
WHERE e.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
OPTIONAL MATCH (lps)<-[:ENDPOINT_OF]-(other:Node)
WHERE other.id <> e.id
RETURN
  e.id              AS equipment_tag,
  e.label           AS equipment_type,
  lps.id            AS connected_lps,
  collect(DISTINCT other.id)[0..5] AS other_endpoints
ORDER BY equipment_tag
LIMIT 300
