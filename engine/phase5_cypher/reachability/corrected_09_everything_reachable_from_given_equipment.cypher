// ============================================================================
// 09_everything_reachable_from_given_equipment.cypher (CORRECTED)
// REACHABILITY & ISOLATION (ENGINEER VIEW)
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - [:CONNECTED*] → [:ENDPOINT_OF] + [:ADJACENT_VIA_NODES*]
//   - Added pid_id scoping
//
// ============================================================================




/* ============================================================================
   1. Everything reachable from a given equipment
   Engineer question:
   "If I start at this vessel/pump, what can I trace through the drawing?"
   
   CORRECTED: Uses ENDPOINT_OF and ADJACENT_VIA_NODES for semantic reachability
   ============================================================================ */




// Usage example:
//   :params { pid_id: "PID_2", start_equipment: "pump_id_here", max_hops: 12 }

MATCH (start:Node {pid_id: $pid_id})
WHERE start.id = $start_equipment
  AND start.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
MATCH (start)-[:ENDPOINT_OF]->(start_lps:LogicalPipeSegment)
MATCH path = (start_lps)-[:ADJACENT_VIA_NODES*0..20]-(lps:LogicalPipeSegment)
OPTIONAL MATCH (lps)<-[:ENDPOINT_OF]-(endpoint:Node)
RETURN DISTINCT
  lps.id                    AS reachable_lps,
  lps.flow_state            AS flow_state,
  collect(DISTINCT endpoint.id)[0..5] AS endpoint_nodes,
  length(path)              AS lps_hops_away
ORDER BY lps_hops_away ASC
LIMIT 1000
