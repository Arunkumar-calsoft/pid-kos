// ============================================================================
// 10_annotations_not_attached_anything.cypher (CORRECTED)
// CONSISTENCY & DRAWING QUALITY CHECKS (ENGINEER VIEW)
//
// SCHEMA UPDATES APPLIED:
//   - Added pid_id scoping
//
// Purpose: Identify orphaned pattern annotations
// ============================================================================




/* ============================================================================
   5. Annotations not attached to anything
   Engineer question:
   "Are there pattern annotations with no clear reference?"
   
   NOTE: This checks for Annotation nodes (pattern metadata) that don't
   annotate any target. May return 0 if all annotations properly target
   LPS, Node, PipeSegment, or PID entities.
   ============================================================================ */




MATCH (ann:Annotation {pid_id: $pid_id})
WHERE NOT (ann)-[:ANNOTATES]->()
RETURN
  ann.id           AS annotation_id,
  ann.pattern_type AS pattern_type,
  ann.category     AS category,
  ann.source       AS source
ORDER BY annotation_id
LIMIT 200
