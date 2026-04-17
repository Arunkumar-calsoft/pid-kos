// ===================================================================
// 04_which_instruments_attached_lines.cypher (CORRECTED)
// Engineer view: "Which instruments are attached to lines?"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment -> Node (no :Equipment node type)
//   - [:CONNECTED] removed (not in schema)
//   - Added pid_id scoping
// ===================================================================


/* -------------------------------------------------------------------
5. Which annotations are attached to pipe lines (not equipment)?
------------------------------------------------------------------- */
MATCH (ann:Annotation {pid_id: $pid_id})-[:ANNOTATES]->(n:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
WHERE NOT (n.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet'])
RETURN
  ann.id AS annotation_id,
  ann.label AS tag,
  ann.type AS annotation_type,
  coalesce(lps.lps_id,lps.id) AS logical_pipe_segment
ORDER BY logical_pipe_segment
LIMIT 300
