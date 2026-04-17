// ===================================================================
// 03_which_lines_connect_directly_equipment.cypher (CORRECTED)
// Engineer view: "What lines exist and how are they drawn/connected?"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - [:CONNECTED] → [:ENDPOINT_OF]
//   - Added pid_id scoping
//
// Structural only. No flow or operation meaning.
// ===================================================================




/* -------------------------------------------------------------------
7. Which lines connect directly to equipment?
   (Line-to-equipment association via nodes)
   
   CORRECTED: Uses ENDPOINT_OF to find equipment connections
   Pattern: PipeSegment contains Node, Node is endpoint of LPS,
            LPS has other endpoint that is equipment
------------------------------------------------------------------- */




MATCH (ps:PipeSegment {pid_id: $pid_id})-[:CONTAINS]->(n:Node)
MATCH (n)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)<-[:ENDPOINT_OF]-(equip:Node)
WHERE equip.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
RETURN DISTINCT
  ps.id        AS line_id,
  equip.id     AS equipment_id,
  equip.label  AS equipment_type,
  lps.id       AS via_logical_segment
ORDER BY line_id
LIMIT 300
