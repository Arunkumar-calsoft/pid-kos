// ============================================================================
// 08_boundary_interface_count.cypher (CORRECTED)
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
4. Boundary interface count (drawing completeness check)
   Engineer question:
   "How many boundary connections exist on this P&ID?"
============================================================================ */




MATCH (n:Node {pid_id: $pid_id})<-[:CONTAINS]-(ps:PipeSegment)
WITH n, COUNT { (n)-[:PIPE]-() } AS pipe_degree
WHERE pipe_degree <= 2  // Low connectivity suggests boundary
RETURN
  count(DISTINCT n) AS boundary_interface_count
