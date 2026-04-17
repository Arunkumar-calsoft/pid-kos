// ============================================================================
// 09_fully_isolated_symbols.cypher (CORRECTED)
// REACHABILITY & ISOLATION (ENGINEER VIEW)
//
// SCHEMA UPDATES APPLIED:
//   - [:CONNECTED] → [:PIPE] and [:ENDPOINT_OF]
//   - Added pid_id scoping
//
// ============================================================================




/* ============================================================================
   5. Fully isolated symbols (drawing quality check)
   Engineer question:
   "Are there symbols floating on the drawing?"
   
   CORRECTED: Checks for nodes without PIPE or ENDPOINT_OF relationships
   ============================================================================ */




MATCH (n:Node {pid_id: $pid_id})
WHERE NOT EXISTS { MATCH (n)-[:PIPE]-() }
  AND NOT EXISTS { MATCH (n)-[:ENDPOINT_OF]->() }
RETURN
  n.id              AS isolated_symbol,
  labels(n)         AS symbol_type,
  n.label           AS label,
  n.structural_type AS structural_type
ORDER BY isolated_symbol
LIMIT 200
