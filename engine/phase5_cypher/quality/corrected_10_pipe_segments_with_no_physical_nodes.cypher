// ============================================================================
// 10_pipe_segments_with_no_physical_nodes.cypher (CORRECTED)
// CONSISTENCY & DRAWING QUALITY CHECKS (ENGINEER VIEW)
//
// SCHEMA UPDATES APPLIED:
//   - Added pid_id scoping
//
// Purpose: Identify pipe segments without node associations
// ============================================================================




/* ============================================================================
   1. Pipe segments with NO physical nodes
   Engineer question:
   "Are there pipe lines drawn that don't actually connect to anything?"
   ============================================================================ */




MATCH (ps:PipeSegment {pid_id: $pid_id})
WHERE NOT (ps)-[:CONTAINS]->(:Node)
RETURN
  ps.id            AS pipe_segment,
  ps.node_count    AS declared_node_count
ORDER BY pipe_segment
LIMIT 200
