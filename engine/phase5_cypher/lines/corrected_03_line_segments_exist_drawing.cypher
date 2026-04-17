// ===================================================================
// 03_line_segments_exist_drawing.cypher (CORRECTED)
// Engineer view: "What lines exist and how are they drawn/connected?"
//
// SCHEMA UPDATES APPLIED:
//   - Added pid_id scoping
//
// Structural only. No flow or operation meaning.
// ===================================================================




/* -------------------------------------------------------------------
1. What line segments exist on the drawing?
   (Basic line inventory)
------------------------------------------------------------------- */




MATCH (ps:PipeSegment {pid_id: $pid_id})
RETURN
  ps.id              AS line_id,
  ps.component_id    AS line_label,
  ps.geometry_hash   AS geometry_hash,
  ps.node_count      AS node_count,
  ps.segment_status  AS segment_status
ORDER BY line_id
LIMIT 500
