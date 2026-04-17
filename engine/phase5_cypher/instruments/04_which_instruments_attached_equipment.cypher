// ===================================================================
// 04_which_instruments_attached_equipment.cypher (CORRECTED)
// Engineer view: "Which instruments are attached to equipment?"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment -> Node with label IN [equipment_labels]
//   - [:CONNECTED] -> [:PIPE] (geometric adjacency)
//   - Added pid_id scoping
// ===================================================================


/* -------------------------------------------------------------------
4. Which annotations target equipment nodes?
   (Via ANNOTATES -> Node with equipment labels)
------------------------------------------------------------------- */
MATCH (ann:Annotation {pid_id: $pid_id})-[:ANNOTATES]->(n:Node {pid_id: $pid_id})
WHERE n.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
OPTIONAL MATCH (n)-[:PIPE]-(neighbour:Node {pid_id: $pid_id})
RETURN
  n.id      AS equipment_id,
  n.label   AS equipment_type,
  ann.id    AS annotation_id,
  ann.label AS tag,
  ann.type  AS annotation_type,
  collect(DISTINCT neighbour.label)[0..3] AS neighbour_types
ORDER BY equipment_id
LIMIT 300
