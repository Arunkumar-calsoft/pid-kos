// ===================================================================
// 04_instruments_and_annotations.cypher
// Engineer view: “What instruments are shown and where are they drawn?”
// Structural & observational only — no control or process meaning.
// ===================================================================




/* -------------------------------------------------------------------
6. Instrument count by prefix (PI, TI, LT, FT, etc.)
   (Pure tag patterning — no semantics)
------------------------------------------------------------------- */




MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.label IS NOT NULL
WITH substring(ann.label,0,2) AS prefix, count(*) AS count
RETURN prefix, count
ORDER BY count DESC
LIMIT 50
