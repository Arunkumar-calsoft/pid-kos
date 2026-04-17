// ============================================================================
// Question 15.5 — 15. ESV / KAV Annotation Classification
// Engineer question: "What is the ESV vs KAV count breakdown?"
//
// Operation: count
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id}) WHERE ann.category IS NOT NULL RETURN ann.category, count(*) AS total ORDER BY total DESC
