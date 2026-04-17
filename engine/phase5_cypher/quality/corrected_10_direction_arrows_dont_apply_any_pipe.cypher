// ============================================================================
// 10_direction_arrows_dont_apply_any_pipe.cypher (CORRECTED)
// CONSISTENCY & DRAWING QUALITY CHECKS (ENGINEER VIEW)
//
// SCHEMA UPDATES APPLIED:
//   - Arrow-[:FLOW_EVIDENCE] → Evidence pattern (source='phase2_flow_evidence')
//   - Added pid_id scoping
//
// Purpose: Identify orphan arrows
// ============================================================================




/* ============================================================================
   3. Direction arrows that don't apply to any pipe
   Engineer question:
   "Are there arrows floating on the drawing with no clear meaning?"
   
   CORRECTED: Checks if Arrow has Evidence that references any LPS
   ============================================================================ */




MATCH (a:Arrow {pid_id: $pid_id})
WHERE NOT EXISTS {
  MATCH (:LogicalPipeSegment {pid_id: $pid_id})<-[:ABOUT]-(e:Evidence)
  WHERE e.source = 'phase2_flow_evidence' AND e.arrow_id = a.id
}
RETURN
  a.id AS arrow_id
ORDER BY arrow_id
LIMIT 200
