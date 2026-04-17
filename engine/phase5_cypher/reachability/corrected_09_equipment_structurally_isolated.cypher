// ============================================================================
// 09_equipment_structurally_isolated.cypher (CORRECTED)
// REACHABILITY & ISOLATION (ENGINEER VIEW)
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - [:CONNECTED] → [:ENDPOINT_OF]
//   - Added pid_id scoping
//
// ============================================================================




/* ============================================================================
   3. Equipment that is structurally isolated
   Engineer question:
   "Are there symbols drawn that are not connected to anything?"
   
   CORRECTED: Checks for equipment without ENDPOINT_OF relationships
   ============================================================================ */




MATCH (e:Node {pid_id: $pid_id})
WHERE e.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND NOT EXISTS {
    MATCH (e)-[:ENDPOINT_OF]->(:LogicalPipeSegment)
  }
RETURN
  e.id    AS isolated_equipment,
  e.label AS equipment_type
ORDER BY isolated_equipment
LIMIT 200
