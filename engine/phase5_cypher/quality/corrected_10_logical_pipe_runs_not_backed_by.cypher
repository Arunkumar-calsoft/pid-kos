// ============================================================================
// 10_logical_pipe_runs_not_backed_by.cypher (CORRECTED)
// CONSISTENCY & DRAWING QUALITY CHECKS (ENGINEER VIEW)
//
// SCHEMA UPDATES APPLIED:
//   - Added pid_id scoping
//
// Purpose: Identify logical segments without physical backing
// ============================================================================




/* ============================================================================
   2. Logical pipe runs that are not backed by physical piping
   Engineer question:
   "Are there logical pipe runs that don't correspond to drawn pipe lines?"
   ============================================================================ */




MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
WHERE NOT (lps)-[:COVERS]->(:PipeSegment)
RETURN
  lps.id          AS pipe_run,
  lps.flow_state  AS flow_state,
  lps.trace_nodes AS trace_nodes
ORDER BY pipe_run
LIMIT 200
