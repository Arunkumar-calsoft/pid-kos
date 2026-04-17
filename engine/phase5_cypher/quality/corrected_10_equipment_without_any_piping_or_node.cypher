// ============================================================================
// 10_equipment_without_any_piping_or_node.cypher (CORRECTED)
// CONSISTENCY & DRAWING QUALITY CHECKS (ENGINEER VIEW)
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - [:CONNECTED] → [:ENDPOINT_OF]
//   - Added pid_id scoping
//
// Purpose: Detect unconnected equipment
// ============================================================================




/* ============================================================================
   6. Equipment without any piping or node connection
   Engineer question:
   "Are there equipment symbols that are never connected?"
   
   CORRECTED: Uses Node instances and checks ENDPOINT_OF relationship
   ============================================================================ */




MATCH (e:Node {pid_id: $pid_id})
WHERE e.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND NOT EXISTS {
    MATCH (e)-[:ENDPOINT_OF]->(:LogicalPipeSegment)
  }
RETURN
  e.id    AS equipment_id,
  e.label AS equipment_type
ORDER BY equipment_id
LIMIT 200
