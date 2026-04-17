// ===================================================================
// 05_valves_with_only_one_connection.cypher (CORRECTED)
// Engineer view: "Where are valves drawn and how are they placed?"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with valve labels
//   - [:CONNECTED] → [:ENDPOINT_OF]
//   - Added pid_id scoping
//
// Structural only — no operational or control interpretation.
// ===================================================================




/* -------------------------------------------------------------------
5. Valves with only one connection (possible dangling / drawing issue)
   
   CORRECTED: Counts ENDPOINT_OF relationships
------------------------------------------------------------------- */




MATCH (v:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
WHERE v.label IN ['valve']
WITH v, count(DISTINCT lps) AS conn_count
WHERE conn_count = 1
RETURN
  v.id      AS valve_id,
  v.label   AS valve_type,
  conn_count AS lps_connections
ORDER BY valve_id
LIMIT 200
