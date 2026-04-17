// ===================================================================
// 05_valves_connected_pumps.cypher (CORRECTED)
// Engineer view: "Where are valves drawn and how are they placed?"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with valve/pump labels
//   - [:CONNECTED] → [:ENDPOINT_OF] with shared LPS
//   - Added pid_id scoping
//
// Structural only — no operational or control interpretation.
// ===================================================================




/* -------------------------------------------------------------------
2. Valves connected to pumps (topological adjacency only)
   
   CORRECTED: Uses shared LPS to find valve-pump connections
------------------------------------------------------------------- */




MATCH (v:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)<-[:ENDPOINT_OF]-(p:Node)
WHERE v.label = 'valve'
  AND p.label = 'tank' AND p.functional_label = 'pump'
RETURN DISTINCT
  v.id      AS valve_id,
  v.label   AS valve_type,
  p.id      AS pump_id,
  lps.id    AS via_lps
ORDER BY valve_id
LIMIT 300
