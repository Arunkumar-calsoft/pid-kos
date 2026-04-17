// ============================================================================
// 08_pipe_segments_terminating_at_drawing_boundary.cypher (CORRECTED)
// EXTERNAL INTERFACES / BATTERY LIMITS (ENGINEER VIEW)
//
// SCHEMA UPDATES APPLIED:
//   - [:CONNECTED] → [:PIPE] (geometric edge connectivity)
//   - Added pid_id scoping
//
// Definition (As-Drawn):
//   A boundary / external interface is a Node that:
//     • participates in a PipeSegment (via CONTAINS)
//     • has low PIPE degree (incomplete topology within this P&ID)
//
// This reflects drawing limits (off-page, tie-in, battery limit),
// NOT plant semantics.
//
// Scope:
//   • Inspection only
//   • No inference
//   • No updates
// ============================================================================




/* ============================================================================
3. Pipe segments terminating at the drawing boundary
   Engineer question:
   "Which drawn pipe segments leave the P&ID boundary?"
============================================================================ */




MATCH (ps:PipeSegment {pid_id: $pid_id})-[:CONTAINS]->(n:Node)
WITH ps, n, COUNT { (n)-[:PIPE]-() } AS pipe_degree
WHERE pipe_degree <= 2  // Low connectivity suggests boundary
RETURN
  ps.id       AS pipe_segment,
  n.id        AS boundary_node,
  n.label     AS boundary_label,
  pipe_degree AS node_connectivity
ORDER BY pipe_segment
LIMIT 200
