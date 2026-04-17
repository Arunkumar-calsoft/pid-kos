// ===================================================================
// 04_annotations_exist_drawing.cypher (CORRECTED)
// Engineer view: "What annotations exist on the drawing?"
//
// SCHEMA UPDATES APPLIED:
//   - Added pid_id scoping
//   - Removed non-existent ann.kind property
// ===================================================================


/* -------------------------------------------------------------------
1. What annotations (instruments / notes) exist on the drawing?
------------------------------------------------------------------- */
MATCH (ann:Annotation {pid_id: $pid_id})
RETURN
  ann.id        AS annotation_id,
  ann.label     AS tag,
  ann.type      AS annotation_type,
  ann.intent    AS intent,
  ann.first_seen AS first_seen
ORDER BY tag
LIMIT 300
