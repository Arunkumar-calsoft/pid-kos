// ============================================================================
// 06_pipe_runs_explicitly_show_flow_direction.cypher (CORRECTED)
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
1. Pipe runs that explicitly show flow direction
   Engineer question:
     "Which pipe runs have direction arrows drawn?"
--------------------------------------------------------------------------- */




MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})<-[:ABOUT]-(e:Evidence)
WHERE e.source = 'phase2_flow_evidence'
WITH lps, collect(DISTINCT e.arrow_id) AS arrow_ids
RETURN
  lps.id            AS pipe_run,
  arrow_ids         AS arrow_ids,
  size(arrow_ids)   AS arrow_count,
  lps.flow_state    AS phase4_flow_state,
  lps.flow_direction AS phase4_direction
ORDER BY arrow_count DESC
LIMIT 200
