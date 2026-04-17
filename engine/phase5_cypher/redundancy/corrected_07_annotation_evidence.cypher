// ============================================================================
// 07_annotation_evidence.cypher (CORRECTED)
// ENGINEER VERIFICATION (READ-ONLY)
//
// SCHEMA UPDATES APPLIED:
//   - Added pid_id scoping
//
// Source of truth: P&ID drawing semantics as used by engineers
// Scope: Inspection only — NO inference, NO updates, NO assertions
// ============================================================================




/* Annotation → Evidence
   
   Shows which Annotations are backed by which Evidence nodes.
   This links Phase 3 pattern detections to their underlying observations.
*/




MATCH (ann:Annotation {pid_id: $pid_id})-[:SUPPORTED_BY]->(ev:Evidence)
RETURN
  ann.id                AS annotation_id,
  ann.pattern_type      AS pattern_type,
  ann.category          AS category,
  ev.id                 AS evidence_id,
  ev.source             AS evidence_source,
  ev.arrow_id           AS arrow_id,
  ev.confidence         AS confidence,
  ev.cosine_alignment   AS cosine_alignment,
  ev.observed_direction AS observed_direction
ORDER BY ev.confidence DESC
LIMIT 200
