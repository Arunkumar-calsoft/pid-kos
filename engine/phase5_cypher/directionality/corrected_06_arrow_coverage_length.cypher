// ============================================================================
// 06_arrow_coverage_length.cypher (CORRECTED)
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
4. Arrow coverage length
   Engineer question:
     "Does an arrow apply to a short section or a long run?"
--------------------------------------------------------------------------- */




MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})<-[:ABOUT]-(e:Evidence)
WHERE e.source = 'phase2_flow_evidence'
OPTIONAL MATCH (lps)-[:COVERS]->(ps:PipeSegment)
RETURN
  e.arrow_id                  AS arrow_id,
  coalesce(lps.id)            AS pipe_run,
  count(DISTINCT ps)          AS covered_pipe_segments,
  lps.length                  AS lps_length
ORDER BY covered_pipe_segments DESC, lps_length DESC
LIMIT 200
