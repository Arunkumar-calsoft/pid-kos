// ===================================================================
// 04_instruments_without_clear_host.cypher (CORRECTED)
// Engineer view: "Floating annotations with no target node"
//
// SCHEMA UPDATES APPLIED:
//   - Added pid_id scoping
// ===================================================================


/* -------------------------------------------------------------------
8. Annotations without a clear host (floating annotations)
------------------------------------------------------------------- */
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE NOT (ann)-[:ANNOTATES]->(:Node)
RETURN
  ann.id    AS annotation_id,
  ann.label AS tag,
  ann.type  AS annotation_type
ORDER BY annotation_id
LIMIT 200
