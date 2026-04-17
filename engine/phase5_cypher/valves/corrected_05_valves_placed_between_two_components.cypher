// ===================================================================
// 05_valves_placed_between_two_components.cypher (CORRECTED)
// ===================================================================

MATCH (v:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps1:LogicalPipeSegment)<-[:ENDPOINT_OF]-(a:Node)
MATCH (v)-[:ENDPOINT_OF]->(lps2:LogicalPipeSegment)<-[:ENDPOINT_OF]-(b:Node)
WHERE v.label IN ['valve']
  AND lps1.id <> lps2.id
  AND a.id <> v.id
  AND b.id <> v.id
  AND a.id < b.id  // Avoid duplicates
RETURN
  v.id      AS valve_id,
  v.label   AS valve_type,
  a.id      AS left_component,
  a.label   AS left_type,
  b.id      AS right_component,
  b.label   AS right_type
ORDER BY valve_id
LIMIT 300;
