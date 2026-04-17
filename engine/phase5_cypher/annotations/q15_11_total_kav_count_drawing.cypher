// ============================================================================
// Question 15.11 — 15. ESV / KAV Annotation Classification
// Engineer question: "What is the total KAV count for this drawing?"
//
// Operation: count
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id})-[:ANNOTATES]->(p:PID {pid_id:$pid_id}) RETURN ann.kav_total
