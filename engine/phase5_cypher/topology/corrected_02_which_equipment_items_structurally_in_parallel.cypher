// ===================================================================
// 02_which_equipment_items_structurally_in_parallel.cypher (CORRECTED)
// Engineer view: "How are things connected on this P&ID?"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - [:CONNECTED] → [:ENDPOINT_OF] with shared LPS
//   - Added pid_id scoping
//
// Pure topology. No flow meaning. Read-only.
// ===================================================================




// Required keywords: parallel
/* -------------------------------------------------------------------
6. Which equipment items are structurally in parallel?
   (More than one shared LPS - redundant paths)
   
   CORRECTED: Equipment with multiple shared LPS connections
------------------------------------------------------------------- */




MATCH (e1:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)<-[:ENDPOINT_OF]-(e2:Node)
WHERE e1.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND e2.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND e1.id < e2.id
WITH e1, e2, count(DISTINCT lps) AS shared_lps_count
WHERE shared_lps_count > 1
RETURN
  e1.id                 AS equipment_A,
  e2.id                 AS equipment_B,
  shared_lps_count      AS parallel_connection_points
ORDER BY parallel_connection_points DESC
LIMIT 100
