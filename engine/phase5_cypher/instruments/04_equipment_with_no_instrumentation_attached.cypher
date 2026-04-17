// ===================================================================
// 04_equipment_with_no_instrumentation_attached.cypher (CORRECTED)
// Engineer view: "Equipment with no instrumentation attached"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment -> Node with label IN [equipment_labels]
//   - [:CONNECTED] removed (not in schema)
//   - Added pid_id scoping
// ===================================================================


/* -------------------------------------------------------------------
7. Equipment nodes with no annotations attached
   (Common drawing quality check)
------------------------------------------------------------------- */
MATCH (e:Node {pid_id: $pid_id})
WHERE e.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND NOT EXISTS {
    MATCH (ann:Annotation {pid_id: $pid_id})-[:ANNOTATES]->(e)
  }
RETURN
  e.id    AS equipment_id,
  e.label AS equipment_type
ORDER BY equipment_id
LIMIT 200
