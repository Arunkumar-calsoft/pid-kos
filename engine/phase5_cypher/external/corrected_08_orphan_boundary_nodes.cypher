// ============================================================================
// 08_orphan_boundary_nodes.cypher (CORRECTED)
// EXTERNAL INTERFACES / BATTERY LIMITS (ENGINEER VIEW)
//
// SCHEMA UPDATES APPLIED:
//   - [:CONNECTED] → [:PIPE] and [:ENDPOINT_OF] relationships
//   - Equipment nodes → Node with label IN [equipment_labels]
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
5. Orphan boundary nodes (quality / extraction check)
   Engineer question:
   "Are there boundary nodes not connected to any equipment?"
============================================================================ */




MATCH (n:Node {pid_id: $pid_id})<-[:CONTAINS]-(ps:PipeSegment)
WITH n, COUNT { (n)-[:PIPE]-() } AS pipe_degree
WHERE pipe_degree <= 2  // Boundary node
  AND NOT EXISTS {
    // Check if this node connects (via shared LPS) to any equipment
    MATCH (n)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)<-[:ENDPOINT_OF]-(equip:Node)
    WHERE equip.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  }
RETURN
  n.id    AS orphan_boundary_node,
  n.label AS label,
  pipe_degree AS connectivity
ORDER BY pipe_degree, n.id
LIMIT 100
