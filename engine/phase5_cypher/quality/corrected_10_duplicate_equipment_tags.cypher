// ============================================================================
// 10_duplicate_equipment_tags.cypher (CORRECTED)
// CONSISTENCY & DRAWING QUALITY CHECKS (ENGINEER VIEW)
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - Added pid_id scoping
//
// Purpose: Detect duplicate equipment tags
// ============================================================================




/* ============================================================================
   4. Duplicate equipment tags
   Engineer question:
   "Are there two symbols with the same tag ID?"
   
   CORRECTED: Uses Node instances with equipment labels
   ============================================================================ */




MATCH (e:Node {pid_id: $pid_id})
WHERE e.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
WITH e.id AS tag_id, count(*) AS occurrences
WHERE tag_id IS NOT NULL AND occurrences > 1
RETURN
  tag_id,
  occurrences
ORDER BY occurrences DESC
LIMIT 100
