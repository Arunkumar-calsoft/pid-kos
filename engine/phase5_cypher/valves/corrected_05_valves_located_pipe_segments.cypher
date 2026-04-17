// ===================================================================
// 05_valves_located_pipe_segments.cypher (CORRECTED)
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
4. Valves located on pipe segments
   (Multiple valves on same line segment?)
   
   CORRECTED: Uses PipeSegment CONTAINS nodes + valve ENDPOINT_OF
------------------------------------------------------------------- */




MATCH (ps:PipeSegment {pid_id: $pid_id})-[:CONTAINS]->(n:Node)
MATCH (n)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)<-[:ENDPOINT_OF]-(v:Node)
WHERE v.label IN ['valve']
RETURN
  ps.id                 AS pipe_segment,
  count(DISTINCT v)     AS valve_count,
  collect(DISTINCT v.id)[0..10] AS valve_sample
ORDER BY valve_count DESC
LIMIT 200
