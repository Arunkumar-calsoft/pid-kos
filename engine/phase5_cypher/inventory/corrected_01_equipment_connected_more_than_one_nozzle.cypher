// ===================================================================
// 01_equipment_connected_more_than_one_nozzle.cypher (CORRECTED)
// Engineer view: "What equipment exists on this P&ID and how is it used?"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - [:CONNECTED]-(n:Node) → [:ENDPOINT_OF]->(lps:LogicalPipeSegment)
//   - Added pid_id scoping
//
// Read-only. No assumptions, no inference.
// ===================================================================




// Required keywords: nozzle
/* -------------------------------------------------------------------
5. What equipment is connected to more than one nozzle / connector?
   (Typical for vessels, exchangers, headers)
   
   NOTE: Uses ENDPOINT_OF to count LPS connections
------------------------------------------------------------------- */




MATCH (e:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
WHERE e.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
WITH e, count(DISTINCT lps) AS connection_count
WHERE connection_count > 1
RETURN
  e.id             AS equipment_tag,
  e.label          AS equipment_type,
  connection_count AS lps_connections,
  e.flow_state     AS phase4_flow_state
ORDER BY connection_count DESC, equipment_tag
LIMIT 200
