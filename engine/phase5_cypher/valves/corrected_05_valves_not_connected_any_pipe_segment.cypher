// ===================================================================
// 05_valves_not_connected_any_pipe_segment.cypher (CORRECTED)
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
6. Valves not connected to any pipe segment
   (Connected to LPS, but LPS nodes not contained in PipeSegment)
   
   CORRECTED: Checks if valve's LPS endpoints connect to PipeSegments
------------------------------------------------------------------- */




MATCH (v:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
WHERE v.label IN ['valve']
  AND NOT EXISTS {
    MATCH (lps)-[:COVERS]->(:PipeSegment)
  }
RETURN
  v.id    AS valve_id,
  v.label AS valve_type,
  lps.id  AS lps_id
ORDER BY valve_id
LIMIT 200
