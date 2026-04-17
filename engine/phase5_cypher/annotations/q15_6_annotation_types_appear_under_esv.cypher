// ============================================================================
// Question 15.6 — 15. ESV / KAV Annotation Classification
// Engineer question: "What Annotation types appear under ESV?"
//
// Operation: count
// Required keywords: esv
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {category:'ESV', pid_id:$pid_id}) RETURN ann.type, count(*) AS total ORDER BY total DESC
