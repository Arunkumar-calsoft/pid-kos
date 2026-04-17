// ============================================================================
// 08_equipment_connected_boundary_interfaces.cypher (CORRECTED)
// EXTERNAL INTERFACES / BATTERY LIMITS (ENGINEER VIEW)
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - [:CONNECTED] → [:PIPE] relationship (geometric connectivity)
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
2. Equipment connected to boundary interfaces
   Engineer question:
   "Which equipment ties into a drawing boundary?"
============================================================================ */




MATCH (e:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
WHERE e.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
// Find nodes connected to this equipment's LPS endpoints
MATCH (lps)-[:ENDPOINT_OF]-(boundary_node:Node {pid_id: $pid_id})
WHERE boundary_node.id <> e.id
WITH e, boundary_node, COUNT { (boundary_node)-[:PIPE]-() } AS pipe_degree
WHERE pipe_degree <= 2  // Low connectivity suggests boundary
RETURN DISTINCT
  e.id                    AS equipment,
  e.label                 AS equipment_type,
  boundary_node.id        AS boundary_node,
  boundary_node.label     AS boundary_label,
  pipe_degree             AS boundary_connectivity
ORDER BY equipment, pipe_degree
LIMIT 200
