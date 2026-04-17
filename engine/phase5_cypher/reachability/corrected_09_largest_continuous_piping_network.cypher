// ============================================================================
// 09_largest_continuous_piping_network.cypher (CORRECTED)
// REACHABILITY & ISOLATION (ENGINEER VIEW)
//
// SCHEMA UPDATES APPLIED:
//   - component_id is NULL - uses JOINS_AT to find connected components
//   - Added pid_id scoping
//
// ============================================================================




/* ============================================================================
   2. Largest continuous piping network
   Engineer question:
   "What is the main connected piping system on this P&ID?"
   
   NOTE: component_id is currently NULL for all PipeSegments.
   Alternative: Use connected components via JOINS_AT
   ============================================================================ */




MATCH (ps:PipeSegment {pid_id: $pid_id})-[:JOINS_AT*0..10]-(connected:PipeSegment {pid_id: $pid_id})
WITH ps.id AS representative_segment, count(DISTINCT connected) AS network_size
RETURN representative_segment, network_size
ORDER BY network_size DESC
LIMIT 10
