// ============================================================================
// Question 15.12 — 15. ESV / KAV Annotation Classification
// Engineer question: "How many distinct ESV types are on this drawing?"
//
// Operation: count
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id})-[:ANNOTATES]->(p:PID {pid_id:$pid_id}) RETURN ann.esv_types
