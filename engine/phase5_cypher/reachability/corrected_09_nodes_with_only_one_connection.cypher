// ============================================================================
// 09_nodes_with_only_one_connection.cypher (CORRECTED)
// REACHABILITY & ISOLATION (ENGINEER VIEW)
//
// SCHEMA UPDATES APPLIED:
//   - [:CONNECTED] → [:PIPE]
//   - Added pid_id scoping
//
// ============================================================================




/* ============================================================================
   4. Nodes with only one connection (dead-ends)
   Engineer question:
   "Where does piping terminate without continuing?"
   
   CORRECTED: Uses PIPE relationship for geometric connectivity
   ============================================================================ */




MATCH (n:Node {pid_id: $pid_id})-[:PIPE]-(x)
WITH n, count(x) AS degree
WHERE degree = 1
RETURN
  n.id              AS dead_end_node,
  n.label           AS label,
  n.structural_type AS type
ORDER BY dead_end_node
LIMIT 200
