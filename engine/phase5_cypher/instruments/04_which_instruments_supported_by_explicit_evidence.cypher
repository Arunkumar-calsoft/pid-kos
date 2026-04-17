// ===================================================================
// 04_instruments_and_annotations.cypher
// Engineer view: “What instruments are shown and where are they drawn?”
// Structural & observational only — no control or process meaning.
// ===================================================================




/* -------------------------------------------------------------------
3. Which instruments are supported by explicit evidence?
   (Arrow, symbol alignment, observation)
------------------------------------------------------------------- */




MATCH (ann:Annotation {pid_id: $pid_id})-[:SUPPORTED_BY]->(ev:Evidence)
RETURN
  ann.id         AS annotation_id,
  ann.label      AS tag,
  ev.id          AS evidence_id,
  ev.arrow_id    AS arrow_id,
  ev.observed_direction AS observed_direction,
  ev.confidence  AS confidence
ORDER BY confidence DESC
LIMIT 300
