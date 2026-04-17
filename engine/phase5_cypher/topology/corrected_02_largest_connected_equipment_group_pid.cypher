// ===================================================================
// 02_largest_connected_equipment_group_pid.cypher (CORRECTED)
// Engineer view: "How are things connected on this P&ID?"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - Variable-length paths → ADJACENT_VIA_NODES between LPS
//   - Added pid_id scoping
//
// Pure topology. No flow meaning. Read-only.
// ===================================================================




// Required keywords: largest, group
/* -------------------------------------------------------------------
8. What is the largest connected equipment group on the P&ID?
   (Overall drawing connectivity health via LPS network)
   
   CORRECTED: Uses LPS network to find connected components
------------------------------------------------------------------- */




MATCH (e:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(start_lps:LogicalPipeSegment)
WHERE e.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
WITH e, start_lps ORDER BY e.id LIMIT 50
WITH e, size([(start_lps)-[:ADJACENT_VIA_NODES*0..8]-(lps) | lps]) AS component_size
RETURN
  e.id            AS seed_equipment,
  e.label         AS equipment_type,
  component_size  AS connected_lps_count
ORDER BY component_size DESC
LIMIT 10
