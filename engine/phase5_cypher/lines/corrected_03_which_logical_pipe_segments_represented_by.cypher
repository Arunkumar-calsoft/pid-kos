// ===================================================================
// 03_which_logical_pipe_segments_represented_by.cypher (CORRECTED)
// Engineer view: "What lines exist and how are they drawn/connected?"
//
// SCHEMA UPDATES APPLIED:
//   - Added pid_id scoping
//   - Uses COVERS relationship (LPS→PipeSegment)
//
// Structural only. No flow or operation meaning.
// ===================================================================




/* -------------------------------------------------------------------
3. Which logical pipe segments are represented by each line?
   (Logical segmentation as drawn)
   
   NOTE: Uses COVERS relationship (LPS covers PipeSegment)
------------------------------------------------------------------- */




MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})-[:COVERS]->(ps:PipeSegment)
RETURN
  ps.id           AS line_id,
  lps.id          AS logical_segment_id,
  lps.flow_state  AS phase4_flow_state,
  lps.flow_direction AS phase4_direction
ORDER BY line_id
LIMIT 500
