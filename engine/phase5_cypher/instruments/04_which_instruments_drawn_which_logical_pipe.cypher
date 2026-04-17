// ===================================================================
// 04_instruments_and_annotations.cypher
// Engineer view: “What instruments are shown and where are they drawn?”
// Structural & observational only — no control or process meaning.
// ===================================================================




/* -------------------------------------------------------------------
2. Which instruments are drawn on which logical pipe segments?
   (Instrument-to-line association)
------------------------------------------------------------------- */




MATCH (ann:Annotation {pid_id: $pid_id})-[:ANNOTATES]->(lps:LogicalPipeSegment)
RETURN
  ann.id AS annotation_id,
  ann.label AS tag,
  ann.type AS annotation_type,
  coalesce(lps.lps_id,lps.id) AS logical_pipe_segment,
  lps.flow_state              AS drawn_flow_state
ORDER BY logical_pipe_segment
LIMIT 300
