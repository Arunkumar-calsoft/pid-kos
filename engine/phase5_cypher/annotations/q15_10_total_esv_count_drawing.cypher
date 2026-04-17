// ============================================================================
// Question 15.10 — 15. ESV / KAV Annotation Classification
// Engineer question: "What is the total ESV count for this drawing?"
//
// Operation: count
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id, source:'phase3_structural_frequencies', pattern_type:'__summary__'}) RETURN ann.esv_total AS esv_total, ann.kav_total AS kav_total
