// ===================================================================
// 03_where_do_lines_branch_or_join.cypher (CORRECTED)
// Engineer view: "What lines exist and how are they drawn/connected?"
//
// SCHEMA UPDATES APPLIED:
//   - Added pid_id scoping
//
// NOTE: JOINS_AT is CORRECT for PipeSegment layer
// Structural only. No flow or operation meaning.
// ===================================================================




/* -------------------------------------------------------------------
5. Where do lines branch or join other lines?
   (Tees, reducers, merges — structural only)
   
   NOTE: JOINS_AT connects PipeSegment to PipeSegment (geometric layer)
   This is CORRECT for this query (not ADJACENT_VIA_NODES which is LPS layer)
------------------------------------------------------------------- */




MATCH (ps:PipeSegment {pid_id: $pid_id})-[j:JOINS_AT]->(other:PipeSegment)
RETURN
  ps.id          AS from_line,
  other.id       AS to_line,
  j.kind         AS join_kind,
  j.trace_nodes  AS trace_nodes
ORDER BY from_line
LIMIT 300
