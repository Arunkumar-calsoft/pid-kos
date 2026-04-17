// ===================================================================
// 02_other_equipment_directly_connected_equipment.cypher (CORRECTED)
// Engineer view: "How are things connected on this P&ID?"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - [:CONNECTED] → [:ENDPOINT_OF] with shared LPS
//   - Added pid_id scoping
//
// Pure topology. No flow meaning. Read-only.
// ===================================================================




// Required keywords: other
/* -------------------------------------------------------------------
2. What other equipment is directly connected to each equipment?
   (Equipment-to-equipment adjacency via shared LPS)
   
   CORRECTED: Uses shared LogicalPipeSegment for adjacency
------------------------------------------------------------------- */




MATCH (e1:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)<-[:ENDPOINT_OF]-(e2:Node)
WHERE e1.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND e2.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND e1.id < e2.id  // Avoid duplicates
RETURN
  e1.id     AS equipment_A,
  e1.label  AS type_A,
  e2.id     AS equipment_B,
  e2.label  AS type_B,
  lps.id    AS via_lps
ORDER BY equipment_A, equipment_B
LIMIT 300
