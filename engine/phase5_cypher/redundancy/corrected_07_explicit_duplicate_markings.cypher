// ============================================================================
// 07_explicit_duplicate_markings.cypher (CORRECTED)
// ENGINEER VERIFICATION (READ-ONLY)
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - Added pid_id scoping
//
// NOTE: duplicate_of property is not in current schema.
//       This query may return 0 rows until OCR/tag phase adds it.
//
// Source of truth: P&ID drawing semantics as used by engineers
// Scope: Inspection only — NO inference, NO updates, NO assertions
// ============================================================================




/* Explicit duplicate markings
   
   Checks for equipment marked as duplicates of other equipment.
   Used when P&ID explicitly notes "TYPICAL" or references another tag.
*/




MATCH (e:Node {pid_id: $pid_id})
WHERE e.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND properties(e).duplicate_of IS NOT NULL
RETURN
  e.id                          AS equipment,
  e.label                       AS equipment_type,
  properties(e).duplicate_of   AS duplicate_of_tag
ORDER BY equipment
LIMIT 200
