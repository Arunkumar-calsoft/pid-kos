// ============================================================================
// 06_pipe_runs_with_multiple_arrows.cypher (CORRECTED)
// Engineer View — AS-DRAWN flow indication on the P&ID
//
// SCHEMA UPDATES APPLIED:
//   - Arrow-[:FLOW_EVIDENCE]->LPS → Evidence-[:ABOUT]->LPS (source='phase2_flow_evidence')
//   - Added pid_id scoping
//
// This file answers only:
//   "What direction information is explicitly drawn on the diagram?"
//
// NO inference
// NO operational meaning
// NO assumptions about real flow
// ============================================================================




/* ---------------------------------------------------------------------------
3. Pipe runs with MULTIPLE arrows
   Engineer question:
     "Are there conflicting or repeated arrows on the same run?"
--------------------------------------------------------------------------- */




MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})<-[:ABOUT]-(e:Evidence)
WHERE e.source = 'phase2_flow_evidence'
WITH lps, collect(DISTINCT e.arrow_id) AS arrows, 
     collect(DISTINCT e.observed_direction) AS directions
WHERE size(arrows) > 1
RETURN
  lps.id                  AS pipe_run,
  arrows                  AS arrow_ids,
  size(arrows)            AS arrow_count,
  directions              AS observed_directions,
  CASE 
    WHEN size(directions) > 1 THEN true 
    ELSE false 
  END                     AS has_conflicting_directions,
  lps.flow_state          AS phase4_flow_state,
  lps.flow_direction      AS phase4_direction
ORDER BY arrow_count DESC, has_conflicting_directions DESC
LIMIT 100
