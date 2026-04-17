// ===================================================================
// 02_all_equipmenttoequipment_paths_drawing.cypher (CORRECTED)
// Engineer view: "How are things connected on this P&ID?"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - Variable-length paths → ADJACENT_VIA_NODES between LPS
//   - Added pid_id scoping
//
// Pure topology. No flow meaning. Read-only.
// ===================================================================




// Required keywords: path
/* -------------------------------------------------------------------
4. What are all equipment-to-equipment paths (bounded) on the drawing?
   (General reachability via LPS network)
   
   CORRECTED: Uses ADJACENT_VIA_NODES for semantic traversal
------------------------------------------------------------------- */




MATCH (a:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(a_lps:LogicalPipeSegment)
WHERE a.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
MATCH (b:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(b_lps:LogicalPipeSegment)
WHERE b.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND a.id < b.id
  AND a_lps.id <> b_lps.id
MATCH p = shortestPath((a_lps)-[:ADJACENT_VIA_NODES*..10]-(b_lps))
RETURN
  a.id          AS from_equipment,
  b.id          AS to_equipment,
  length(p)     AS lps_hop_count
ORDER BY lps_hop_count
LIMIT 50
