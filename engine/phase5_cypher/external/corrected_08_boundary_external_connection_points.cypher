// ============================================================================
// 08_boundary_external_connection_points.cypher (CORRECTED)
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
1. Boundary / external connection points
   Engineer question:
   "Where does this P&ID connect to something outside this drawing?"

   Structural rule:
     • Node is part of a PipeSegment
     • Node has exactly ONE or TWO PIPE neighbors (low connectivity)
============================================================================ */




MATCH (n:Node {pid_id: $pid_id})<-[:CONTAINS]-(ps:PipeSegment)
WITH n, COUNT { (n)-[:PIPE]-() } AS pipe_degree
WHERE pipe_degree <= 2  // Low connectivity suggests boundary
RETURN
  n.id                 AS interface_id,
  n.label              AS drawing_label,
  pipe_degree          AS pipe_connectivity,
  n.bbox               AS drawing_location
ORDER BY pipe_degree, interface_id
LIMIT 200
