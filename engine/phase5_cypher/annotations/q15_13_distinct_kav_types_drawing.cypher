// ============================================================================
// Question 15.13 — 15. ESV / KAV Annotation Classification
// Engineer question: "How many distinct KAV types are on this drawing?"
//
// Operation: count
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id})-[:ANNOTATES]->(p:PID {pid_id:$pid_id}) RETURN ann.kav_types
