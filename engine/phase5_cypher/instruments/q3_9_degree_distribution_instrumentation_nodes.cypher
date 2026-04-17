// ============================================================================
// Question 3.9 — 3. Instrument Attachment
// Engineer question: "Show the degree distribution of instrumentation nodes."
//
// Operation: count
// Intent: instrument_attachment
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (i:Node {label:'instrumentation', pid_id:$pid_id}) WITH size([(i)-[:PIPE]-() |1]) AS deg RETURN deg, count(*) AS total ORDER BY deg
