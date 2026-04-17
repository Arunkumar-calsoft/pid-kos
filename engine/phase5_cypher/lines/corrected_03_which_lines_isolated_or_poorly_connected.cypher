// ===================================================================
// 03_which_lines_isolated_or_poorly_connected.cypher (CORRECTED)
// Engineer view: "What lines exist and how are they drawn/connected?"
//
// SCHEMA UPDATES APPLIED:
//   - Added pid_id scoping
//
// Structural only. No flow or operation meaning.
// ===================================================================




/* -------------------------------------------------------------------
8. Which lines are isolated or poorly connected?
   (Drawing completeness check)
------------------------------------------------------------------- */




MATCH (ps:PipeSegment {pid_id: $pid_id})
WHERE NOT (ps)-[:JOINS_AT]-(:PipeSegment)
RETURN
  ps.id            AS isolated_line,
  ps.node_count    AS node_count,
  ps.segment_status AS segment_status
ORDER BY isolated_line
LIMIT 200
