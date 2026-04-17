// ============================================================================
// Question 15.7 — 15. ESV / KAV Annotation Classification
// Engineer question: "What Annotation types appear under KAV?"
//
// Operation: count
// Required keywords: kav
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {category:'KAV', pid_id:$pid_id}) RETURN ann.type, count(*) AS total ORDER BY total DESC
