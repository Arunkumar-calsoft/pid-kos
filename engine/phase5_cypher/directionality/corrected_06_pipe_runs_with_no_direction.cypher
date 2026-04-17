// ============================================================================
// 06_pipe_runs_with_no_direction.cypher (CORRECTED)
// Engineer View — AS-DRAWN flow indication on the P&ID
//
// SCHEMA UPDATES APPLIED:
//   - Arrow-[:FLOW_EVIDENCE]->LPS  →  Evidence-[:ABOUT]->LPS (source='phase2_flow_evidence')
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
2. Pipe runs with NO direction shown
   Engineer question:
     "Which pipe runs do not show any direction on the drawing?"
--------------------------------------------------------------------------- */




MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
WHERE NOT EXISTS {
  MATCH (lps)<-[:ABOUT]-(e:Evidence)
  WHERE e.source = 'phase2_flow_evidence'
}
RETURN
  coalesce(lps.id) AS pipe_run_without_direction,
  lps.length       AS lps_length,
  lps.flow_state   AS phase4_flow_state
ORDER BY lps.length DESC
LIMIT 200
